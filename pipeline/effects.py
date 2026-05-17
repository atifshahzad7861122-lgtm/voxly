import subprocess
from pathlib import Path

from config import EMOJI_MAP, CLIPS_DIR, logger
from utils.ffmpeg import get_video_info, extract_audio_energy
from utils.db import _load_words


def build_emoji_overlays(words: list, clip_duration: float) -> list:
    if not words: return []
    overlays, used_times = [], []
    for w in words:
        word_clean = w.get("word", "").strip().lower().strip(".,!?;:")
        if word_clean not in EMOJI_MAP: continue
        t_start = round(float(w.get("start", 0)), 2)
        t_end   = round(min(t_start + 1.8, clip_duration - 0.3), 2)
        if t_start < 1.0 or t_end <= t_start: continue
        if any(abs(t_start - u) < 3.0 for u in used_times): continue
        used_times.append(t_start)
        label, box_color = EMOJI_MAP[word_clean]
        fi_end   = round(t_start + 0.2, 2)
        fo_start = round(t_end   - 0.2, 2)
        alpha = (
            f"if(lt(t\\,{t_start})\\,0\\,"
            f"if(lt(t\\,{fi_end})\\,(t-{t_start})/0.2\\,"
            f"if(lt(t\\,{fo_start})\\,1\\,"
            f"if(lt(t\\,{t_end})\\,({t_end}-t)/0.2\\,0))))"
        )
        safe_label = label.replace("'", "\\'")
        overlays.append(
            f"drawtext=text='{safe_label}'"
            f":fontcolor=white:fontsize=64:font=Impact"
            f":box=1:boxcolor={box_color}:boxborderw=16"
            f":x=(w-text_w)/2:y=h*0.17"
            f":alpha='{alpha}'"
        )
        if len(overlays) >= 4: break
    return overlays


def find_energy_peaks_in_clip(clip_path: Path, n_peaks: int = 3) -> list:
    try:
        dur, _, _ = get_video_info(clip_path)
    except Exception:
        return []
    energies = extract_audio_energy(clip_path, dur)
    if len(energies) < 5: return []
    sorted_e = sorted(energies, key=lambda x: x[1], reverse=True)
    peaks = []
    for t, _rms in sorted_e:
        if t < 2.0 or t > dur - 3.0: continue
        if all(abs(t - p["time"]) >= 3.0 for p in peaks):
            peaks.append({"time": round(t, 2), "duration": 1.8})
        if len(peaks) >= n_peaks: break
    return peaks


def apply_auto_zoom(clip_path: Path, output: Path, out_w: int = 1080, out_h: int = 1920) -> bool:
    peaks = find_energy_peaks_in_clip(clip_path)
    if not peaks: return False
    zoom_parts = [
        f"between(t\\,{p['time']}\\,{round(p['time']+p['duration'],2)})*0.22"
        for p in peaks
    ]
    zoom_expr = "1+min(0.22\\," + "+".join(zoom_parts) + ")"
    vf = (
        f"crop=w='iw/{zoom_expr}':h='ih/{zoom_expr}':"
        f"x='(iw-iw/{zoom_expr})/2':y='(ih-ih/{zoom_expr})/2',"
        f"scale={out_w}:{out_h}"
    )
    cmd = [
        "ffmpeg", "-i", str(clip_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "copy", "-y", str(output),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        return r.returncode == 0
    except Exception as e:
        logger.error("AutoZoom failed", exc_info=True)
        return False


def apply_speed_ramp(clip_path: Path, output: Path,
                      out_vcodec: str = "libx264", out_acodec: str = "aac",
                      out_extra_flags: list = None) -> bool:
    if out_extra_flags is None: out_extra_flags = ["-movflags", "+faststart"]
    try:
        dur, _, _ = get_video_info(clip_path)
    except Exception:
        return False
    energies = extract_audio_energy(clip_path, dur)
    if len(energies) < 6: return False
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

    if len({s["speed"] for s in merged}) <= 1: return False

    n = len(merged)
    filter_parts, concat_parts = [], []
    for i, seg in enumerate(merged):
        s = round(seg["start"], 3)
        d = round(seg["end"] - seg["start"], 3)
        sp = seg["speed"]
        filter_parts.append(f"[0:v]trim=start={s}:duration={d},setpts=(PTS-STARTPTS)/{sp}[v{i}]")
        filter_parts.append(f"[0:a]atrim=start={s}:duration={d},asetpts=(PTS-STARTPTS),atempo={sp}[a{i}]")
        concat_parts.append(f"[v{i}][a{i}]")
    filter_parts.append("".join(concat_parts) + f"concat=n={n}:v=1:a=1[vout][aout]")

    if out_acodec == "libopus":
        a_flags = ["-c:a", "libopus", "-b:a", "128k"]
    else:
        a_flags = ["-c:a", out_acodec, "-b:a", "128k"]
    cmd = [
        "ffmpeg", "-i", str(clip_path),
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", out_vcodec, "-preset", "ultrafast", "-crf", "26",
        *a_flags, *out_extra_flags,
        "-y", str(output),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        if r.returncode != 0:
            logger.error(f"SpeedRamp FFmpeg failed: {r.stderr.decode(errors='replace')[-400:]}")
        return r.returncode == 0
    except Exception as e:
        logger.error("SpeedRamp exception occurred", exc_info=True)
        return False


def apply_logo_overlay(clip_path: Path, logo_path: Path, cfg: dict, output: Path,
                        out_vcodec: str = "libx264") -> bool:
    corner  = cfg.get("corner", "br")
    opacity = max(0.1, min(1.0, float(cfg.get("opacity", 0.8))))
    size = {"small": 80, "medium": 120, "large": 180}.get(cfg.get("size", "medium"), 120)
    pos = {
        "tl": ("20", "20"), "tr": ("W-w-20", "20"),
        "bl": ("20", "H-h-20"), "br": ("W-w-20", "H-h-20"),
    }
    x, y = pos.get(corner, ("W-w-20", "H-h-20"))
    cmd = [
        "ffmpeg", "-i", str(clip_path), "-i", str(logo_path),
        "-filter_complex",
        f"[1:v]scale={size}:-1,format=rgba,colorchannelmixer=aa={opacity}[logo];"
        f"[0:v][logo]overlay={x}:{y}",
        "-c:v", out_vcodec, "-preset", "ultrafast", "-crf", "26",
        "-c:a", "copy", "-y", str(output),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        return r.returncode == 0
    except Exception as e:
        logger.error("Logo overlay failed", exc_info=True)
        return False
