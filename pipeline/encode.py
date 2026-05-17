import os
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from config import (
    CLIPS_DIR, LOGOS_DIR, RESOLUTION_MAP, DEFAULT_RESOLUTION,
    WHISPER_LANG_PROMPTS, logger,
)
from utils.db import _transcripts, _transcripts_lock, _words_json_path, _save_words
from pipeline.transcribe import transcribe_and_generate_ass
from pipeline.filters import build_unified_vf_chain


def enforce_quality_floor(source_height: int, requested_resolution: str) -> str:
    floor_map = {
        2160: "720p", 1080: "720p", 720: "480p", 480: "480p",
    }
    quality_floor = "480p"
    sorted_thresholds = sorted(floor_map.keys(), reverse=True)
    for threshold in sorted_thresholds:
        if source_height >= threshold:
            quality_floor = floor_map[threshold]
            break
    res_priority = {"480p": 1, "720p": 2, "1080p": 3, "4k": 4}
    requested_priority = res_priority.get(requested_resolution, 2)
    floor_priority = res_priority.get(quality_floor, 1)
    if requested_priority < floor_priority:
        logger.warning(
            f"Requested {requested_resolution} is below quality floor "
            f"for {source_height}p source. Upgrading to {quality_floor}."
        )
        return quality_floor
    return requested_resolution


def encode_clip_two_pass(
    input_path: str, output_path: str, start: float, dur: float,
    out_bitrate: str, out_maxrate: str, out_bufsize: str,
    out_vcodec: str = "libx264", out_preset: str = "slow",
    filter_complex: str = "", extra_inputs: list = None,
    map_v: str = "", map_a: str = "", extra_flags: list = None,
    passlogfile: str = None, out_pix_fmt: str = "yuv420p",
) -> bool:
    if passlogfile is None:
        passlogfile = str(Path(tempfile.gettempdir()) / f"voxly_2pass_{uuid.uuid4().hex}")
    if extra_flags is None: extra_flags = []
    if extra_inputs is None: extra_inputs = []

    try:
        pass1_cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", str(input_path)]
        if extra_inputs: pass1_cmd += extra_inputs
        pass1_cmd += [
            "-t", str(dur),
            "-c:v", out_vcodec, "-preset", out_preset,
            "-b:v", out_bitrate, "-maxrate", out_maxrate, "-bufsize", out_bufsize,
            "-pass", "1", "-passlogfile", passlogfile,
        ]
        if filter_complex:
            pass1_cmd += ["-filter_complex", filter_complex]
            if map_v: pass1_cmd += ["-map", map_v]
        pass1_cmd += ["-an", "-f", "null", "NUL" if platform.system() == "Windows" else "/dev/null"]
        subprocess.run(pass1_cmd, capture_output=True, check=True)

        pass2_cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", str(input_path)]
        if extra_inputs: pass2_cmd += extra_inputs
        pass2_cmd += [
            "-t", str(dur),
            "-c:v", out_vcodec, "-preset", out_preset,
            "-b:v", out_bitrate, "-maxrate", out_maxrate, "-bufsize", out_bufsize,
            "-pass", "2", "-passlogfile", passlogfile,
        ]
        if filter_complex:
            pass2_cmd += ["-filter_complex", filter_complex]
            if map_v: pass2_cmd += ["-map", map_v]
            if map_a: pass2_cmd += ["-map", map_a]
        pass2_cmd += ["-c:a", "aac", "-b:a", "192k", "-pix_fmt", out_pix_fmt]
        pass2_cmd += extra_flags
        pass2_cmd += [str(output_path)]
        subprocess.run(pass2_cmd, capture_output=True, check=True)

        logger.info(f"Two-pass encode complete: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Two-pass encode failed: {e.stderr.decode(errors='replace')}")
        return False
    finally:
        for ext in ["-0.log", "-0.log.mbtree"]:
            try: os.remove(passlogfile + ext)
            except FileNotFoundError: pass


def cut_clip(video_path: Path, start: float, end: float,
             idx: int, width: int, height: int, clip_duration: int,
             mode: str = "fill", captions_enabled: bool = True,
             caption_style: str = "mrbeast", language: str = None,
             audio_enhance: bool = False, custom_style_cfg: dict = None,
             color_grade: str = "none", auto_zoom: bool = False,
             emoji_burst: bool = False, logo_config: dict = None,
             face_focus: bool = False, speed_ramp: bool = False,
             out_width: int = 1080, out_height: int = 1920,
             out_crf: int = 18, out_bitrate: str = "8000k", out_vcodec: str = "libx264",
             out_acodec: str = "aac", out_pix_fmt: str = "yuv420p",
             out_extra_flags: list = None, out_extension: str = ".mp4",
             out_preset: str = "slow", out_maxrate: str = "10000k", out_bufsize: str = "16000k",
             two_pass: bool = False):
    if out_extra_flags is None:
        out_extra_flags = ["-movflags", "+faststart"]
    name = f"short_{idx + 1}_{uuid.uuid4().hex[:6]}{out_extension}"
    out  = CLIPS_DIR / name

    dur = round(end - start, 2)

    if out_vcodec == "libvpx-vp9":
        crf_flags = ["-b:v", "0", "-crf", str(out_crf)]
    else:
        crf_flags = ["-crf", str(out_crf)]

    raw_audio_out = CLIPS_DIR / f"{out.stem}_raw.mp3"
    temp_audio = CLIPS_DIR / f"ta_{idx + 1}_{uuid.uuid4().hex[:6]}.mp3"
    subprocess.run([
        "ffmpeg", "-ss", str(start), "-i", str(video_path),
        "-t", str(dur), "-vn", "-acodec", "libmp3lame", "-q:a", "5",
        "-y", str(temp_audio)
    ], capture_output=True)

    if temp_audio.exists():
        try: shutil.copy2(str(temp_audio), str(raw_audio_out))
        except: pass

    transcript = ""
    ass_path = None
    if captions_enabled:
        try:
            ass_path, transcript = transcribe_and_generate_ass(
                temp_audio, caption_style, language=language, custom_cfg=custom_style_cfg
            )
            srt_src = temp_audio.with_suffix(".srt")
            srt_dst = out.with_suffix(".srt")
            if srt_src.exists(): srt_src.rename(srt_dst)

            with _transcripts_lock:
                if temp_audio.name in _transcripts:
                    _transcripts[name] = _transcripts.pop(temp_audio.name)

            old_json = _words_json_path(temp_audio.name)
            new_json = _words_json_path(name)
            if old_json.exists():
                try: old_json.rename(new_json)
                except: pass
        except Exception as e:
            logger.error("Whisper annotation failed", exc_info=True)

    logo_file = (logo_config.get("filename") or "").strip() if logo_config else ""
    logo_path = LOGOS_DIR / logo_file if logo_file else None

    render_start = time.perf_counter()

    filter_complex_str, extra_inputs, map_v, map_a = build_unified_vf_chain(
        video_path=video_path, start=start, dur=dur,
        width=width, height=height, mode=mode,
        face_focus=face_focus, color_grade=color_grade,
        auto_zoom=auto_zoom, emoji_burst=emoji_burst,
        logo_config=logo_config, logo_path=logo_path,
        ass_path=ass_path, temp_audio=temp_audio,
        speed_ramp=speed_ramp, audio_enhance=audio_enhance,
        out_width=out_width, out_height=out_height, name=name
    )

    success = False
    if two_pass and out_vcodec == "libx264":
        unique_pass_log = str(CLIPS_DIR / f"passlog_{uuid.uuid4().hex[:8]}")
        success = encode_clip_two_pass(
            input_path=video_path, output_path=str(out),
            start=start, dur=dur,
            out_bitrate=out_bitrate, out_maxrate=out_maxrate, out_bufsize=out_bufsize,
            out_vcodec=out_vcodec, out_preset=out_preset,
            filter_complex=filter_complex_str,
            extra_inputs=extra_inputs, map_v=map_v, map_a=map_a,
            extra_flags=out_extra_flags, out_pix_fmt=out_pix_fmt,
            passlogfile=unique_pass_log
        )
        for p_log in CLIPS_DIR.glob(f"passlog_{unique_pass_log}*"):
            try: p_log.unlink()
            except: pass
        if not success:
            logger.warning("Two-pass failed, falling back to single-pass")
        else:
            r_final = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    if not two_pass or (two_pass and not success):
        final_cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", str(video_path)]
        if extra_inputs: final_cmd += extra_inputs
        final_cmd += [
            "-t", str(dur),
            "-filter_complex", filter_complex_str,
            "-map", map_v, "-map", map_a,
        ]

        if out_vcodec == "libvpx-vp9":
            quality_flags = ["-b:v", "0", "-crf", str(out_crf)]
        else:
            quality_flags = ["-crf", str(out_crf), "-preset", out_preset]

        final_cmd += ["-c:v", out_vcodec, *quality_flags,
                       "-b:v", out_bitrate, "-maxrate", out_maxrate, "-bufsize", out_bufsize]

        if out_acodec == "libopus":
            final_cmd += ["-c:a", "libopus", "-b:a", "128k"]
        else:
            final_cmd += ["-c:a", "aac", "-b:a", "192k"]

        final_cmd += out_extra_flags
        final_cmd += ["-pix_fmt", out_pix_fmt, str(out)]

        logger.info(f"Executing Single-pass complex FFmpeg: {' '.join(final_cmd)}")
        r_final = subprocess.run(final_cmd, capture_output=True)

    render_duration = time.perf_counter() - render_start
    logger.info(f"Unified FFmpeg encode completed in {render_duration:.2f}s")

    try:
        if temp_audio.exists(): temp_audio.unlink()
        if ass_path and ass_path.exists():
            shutil.copy2(str(ass_path), str(out.with_suffix(".ass")))
            ass_path.unlink()
    except: pass

    if (not two_pass or (two_pass and not success)) and r_final.returncode != 0:
        if not out.exists():
            subprocess.run(["ffmpeg", "-ss", str(start), "-i", str(video_path),
                            "-t", str(dur), "-c", "copy", "-y", str(out)])
        logger.error(f"[!] Render failed for clip {idx+1}: {r_final.stderr.decode(errors='replace')[-600:]}")

    return out, transcript
