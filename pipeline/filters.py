import os
import subprocess
from pathlib import Path

from config import COLOR_GRADE_FILTERS, logger
from utils.ffmpeg import get_video_info, extract_audio_energy
from utils.db import _load_words
from pipeline.effects import build_emoji_overlays, find_energy_peaks_in_clip
from vision.face_track import build_face_tracking_vf


def detect_content_center(video_path: Path, timestamp: float = 2.0):
    W, H = 80, 45
    cmd = [
        "ffmpeg", "-ss", str(round(timestamp, 2)), "-i", str(video_path),
        "-vframes", "1", "-vf", f"scale={W}:{H}",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        if r.returncode != 0 or len(r.stdout) < W * H:
            return (0.5, 0.42)
        pixels = list(r.stdout)
        total = sum(pixels)
        if total == 0: return (0.5, 0.42)
        cx = sum((i % W) * v for i, v in enumerate(pixels)) / total / W
        cy = sum((i // W) * v for i, v in enumerate(pixels)) / total / H
        return (max(0.2, min(0.8, cx)), max(0.2, min(0.70, cy)))
    except Exception:
        return (0.5, 0.42)


def build_vf_focused(width: int, height: int, cx: float, cy: float,
                      out_w: int = 1080, out_h: int = 1920):
    ratio = 9 / 16
    if width / height > ratio:
        cw = int(height * ratio) & ~1
        ch = height & ~1
        ideal_x = int(cx * width - cw / 2)
        crop_x = max(0, min(width - cw, ideal_x)) & ~1
        return f"crop={cw}:{ch}:{crop_x}:0,scale={out_w}:{out_h}:flags=lanczos"
    else:
        cw = width & ~1
        ch = int(width / ratio) & ~1
        ideal_y = int(cy * height - ch / 2)
        crop_y = max(0, min(height - ch, ideal_y)) & ~1
        return f"crop={cw}:{ch}:0:{crop_y},scale={out_w}:{out_h}:flags=lanczos"


def build_vf(width: int, height: int, out_w: int = 1080, out_h: int = 1920):
    ratio = 9 / 16
    if width / height > ratio:
        cw = int(height * ratio)
        ch = height
        cx = (width - cw) // 2
        cy = 0
    else:
        cw = width
        ch = int(width / ratio)
        cx = 0
        cy = (height - ch) // 2
    cw -= cw % 2
    ch -= ch % 2
    return f"crop={cw}:{ch}:{cx}:{cy},scale={out_w}:{out_h}:flags=lanczos"


def build_vf_pad(width: int, height: int, out_w: int = 1080, out_h: int = 1920):
    return (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    )


def build_unified_vf_chain(
    video_path: Path, start: float, dur: float,
    width: int, height: int, mode: str = "fill",
    face_focus: bool = False, color_grade: str = "none",
    auto_zoom: bool = False, emoji_burst: bool = False,
    logo_config: dict = None, logo_path: Path = None,
    ass_path: Path = None, temp_audio: Path = None,
    speed_ramp: bool = False, audio_enhance: bool = False,
    out_width: int = 1080, out_height: int = 1920, name: str = ""
):
    video_filters = []

    if mode == "pad":
        base_vf = build_vf_pad(width, height, out_w=out_width, out_h=out_height)
    elif face_focus:
        base_vf = build_face_tracking_vf(video_path, start, dur, width, height,
                                          out_w=out_width, out_h=out_height)
    else:
        base_vf = build_vf(width, height, out_w=out_width, out_h=out_height)
    video_filters.append(base_vf)

    cg_filter = COLOR_GRADE_FILTERS.get(color_grade or "none", "")
    if cg_filter:
        video_filters.append(cg_filter)

    if auto_zoom and temp_audio:
        peaks = find_energy_peaks_in_clip(temp_audio)
        if peaks:
            zoom_parts = [
                f"between(t\\,{p['time']}\\,{round(p['time']+p['duration'],2)})*0.22"
                for p in peaks
            ]
            zoom_expr = "1+min(0.22\\," + "+".join(zoom_parts) + ")"
            zoom_vf = (
                f"crop=w='iw/{zoom_expr}':h='ih/{zoom_expr}':"
                f"x='(iw-iw/{zoom_expr})/2':y='(ih-ih/{zoom_expr})/2'"
            )
            video_filters.append(zoom_vf)

    if emoji_burst:
        clip_words = _load_words(name) or (temp_audio and _load_words(temp_audio.name))
        emoji_filters = build_emoji_overlays(clip_words, dur)
        if emoji_filters:
            video_filters.extend(emoji_filters)

    if ass_path and ass_path.exists():
        abs_ass = str(ass_path.absolute())
        if os.name == 'nt':
            escaped_ass = abs_ass.replace("\\", "/").replace(":", "\\:")
            video_filters.append(f"ass='{escaped_ass}'")
        else:
            video_filters.append(f"ass='{abs_ass}'")

    vf_str = ",".join(video_filters)

    extra_inputs = []
    logo_filter_part = ""
    if logo_path and logo_path.exists() and logo_config:
        opacity = max(0.1, min(1.0, float(logo_config.get("opacity", 0.8))))
        size = {"small": 80, "medium": 120, "large": 180}.get(logo_config.get("size", "medium"), 120)
        pos = {"tl": ("20","20"), "tr": ("W-w-20","20"), "bl": ("20","H-h-20"), "br": ("W-w-20","H-h-20")}
        lx, ly = pos.get(logo_config.get("corner", "br"), ("W-w-20", "H-h-20"))
        extra_inputs += ["-i", str(logo_path)]
        logo_filter_part = (
            f"[0:v]{vf_str}[vbase];"
            f"[1:v]scale={size}:-1:flags=lanczos,format=rgba,colorchannelmixer=aa={opacity}[logo];"
            f"[vbase][logo]overlay={lx}:{ly}[vpre_ramp]"
        )
    else:
        logo_filter_part = f"[0:v]{vf_str}[vpre_ramp]"

    audio_af = []
    if audio_enhance:
        audio_af = [
            "highpass=f=80", "afftdn=nf=-25",
            "equalizer=f=250:width_type=q:width=0.7:g=-3",
            "equalizer=f=3500:width_type=q:width=0.8:g=4",
            "treble=g=2:f=8000",
            "acompressor=threshold=0.125:ratio=3:attack=5:release=60:makeup=2",
            "loudnorm=I=-14:TP=-1.5:LRA=7",
        ]

    if audio_af:
        audio_filter_part = f"[0:a]{','.join(audio_af)}[apre_ramp]"
    else:
        audio_filter_part = f"[0:a]anull[apre_ramp]"

    do_speed_ramp = False
    speed_filter_part = ""
    if speed_ramp and temp_audio:
        energies = extract_audio_energy(temp_audio, dur)
        if len(energies) >= 6:
            vals   = [e[1] for e in energies]
            mean_e = sum(vals) / len(vals)
            thresh = mean_e * 0.65

            schedule = [(t, 1.35 if rms < thresh else 1.0) for t, rms in energies]

            segs = []
            s0, sp0 = schedule[0]
            for t, sp in schedule[1:]:
                if sp != sp0:
                    segs.append({"start": s0, "end": t, "speed": sp0})
                    s0, sp0 = t, sp
            segs.append({"start": s0, "end": dur, "speed": sp0})

            MIN_SEG = 2.0
            merged = []
            for seg in segs:
                d = seg["end"] - seg["start"]
                if d < MIN_SEG and merged:
                    merged[-1] = {**merged[-1], "end": seg["end"]}
                else:
                    merged.append(dict(seg))

            if len({s["speed"] for s in merged}) > 1:
                do_speed_ramp = True
                n = len(merged)
                parts = []
                concat_parts = []
                parts.append(f"[vpre_ramp]split={n}" + "".join(f"[vs{i}]" for i in range(n)))
                parts.append(f"[apre_ramp]asplit={n}" + "".join(f"[as{i}]" for i in range(n)))
                for i, seg in enumerate(merged):
                    s = round(seg["start"], 3)
                    d = round(seg["end"] - seg["start"], 3)
                    sp = seg["speed"]
                    parts.append(f"[vs{i}]trim=start={s}:duration={d},setpts=(PTS-STARTPTS)/{sp}[v{i}]")
                    parts.append(f"[as{i}]atrim=start={s}:duration={d},asetpts=(PTS-STARTPTS),atempo={sp}[a{i}]")
                    concat_parts.append(f"[v{i}][a{i}]")
                parts.append("".join(concat_parts) + f"concat=n={n}:v=1:a=1[vout][aout]")
                speed_filter_part = ";".join(parts)

    filter_complex_parts = [logo_filter_part, audio_filter_part]
    if do_speed_ramp:
        filter_complex_parts.append(speed_filter_part)
        map_v = "[vout]"
        map_a = "[aout]"
    else:
        map_v = "[vpre_ramp]"
        map_a = "[apre_ramp]"

    filter_complex_str = ";".join(filter_complex_parts)
    return filter_complex_str, extra_inputs, map_v, map_a
