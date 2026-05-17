import os
import re as _re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import requests

from config import CLIPS_DIR, logger
from utils.fonts import resolve_font_path, escape_font_path
from utils.ffmpeg import get_video_info

_THUMB_FONT = resolve_font_path()
if _THUMB_FONT:
    logger.info(f"[THUMB] Font ready: {_THUMB_FONT}")
else:
    logger.warning("[THUMB] No font found \u2014 thumbnail text overlay disabled.")


def extract_best_thumbnail_frame(video_path: str, output_path: str,
                                  thumb_w: int = 720, thumb_h: int = 1280) -> bool:
    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True)
        duration = float(result.stdout.strip())

        start_pct, end_pct, num_samples = 0.20, 0.80, 8
        timestamps = [
            duration * (start_pct + (end_pct - start_pct) * i / (num_samples - 1))
            for i in range(num_samples)
        ]

        best_frame_path = None
        best_score = -1

        for i, ts in enumerate(timestamps):
            candidate_path = str(output_path).replace(".jpg", f"_cand_{i}.jpg")
            extract_cmd = [
                "ffmpeg", "-y", "-ss", str(ts), "-i", video_path,
                "-vf", f"scale={thumb_w}:{thumb_h}:force_original_aspect_ratio=increase,crop={thumb_w}:{thumb_h}",
                "-frames:v", "1", "-q:v", "2", candidate_path,
            ]
            subprocess.run(extract_cmd, capture_output=True)
            if not os.path.exists(candidate_path): continue

            try:
                score_cmd = [
                    "ffprobe", "-v", "error", "-f", "lavfi",
                    "-i", f"movie={candidate_path.replace(':', '\\\\:')},signalstats",
                    "-show_entries", "frame_tags=lavfi.signalstats.YAVG,lavfi.signalstats.YDIF",
                    "-of", "default=noprint_wrappers=1",
                ]
                score_result = subprocess.run(score_cmd, capture_output=True, text=True)
                output_text = score_result.stdout
                yavg, ydif = 128, 0.1
                for line in output_text.splitlines():
                    if "YAVG" in line: yavg = float(line.split("=")[1])
                    if "YDIF" in line: ydif = float(line.split("=")[1])
                brightness_score = max(0, 100 - abs(yavg - 110) * 1.5)
                contrast_score = min(100, ydif * 20)
                total_score = brightness_score * 0.6 + contrast_score * 0.4
            except:
                total_score = 10

            if total_score > best_score:
                best_score = total_score
                best_frame_path = candidate_path

        if best_frame_path and os.path.exists(best_frame_path):
            shutil.copy2(best_frame_path, output_path)
            for i in range(num_samples):
                cand = str(output_path).replace(".jpg", f"_cand_{i}.jpg")
                if os.path.exists(cand) and cand != best_frame_path:
                    os.remove(cand)
            if os.path.exists(best_frame_path) and best_frame_path != output_path:
                os.remove(best_frame_path)
            logger.info(f"Best fallback frame selected (score={best_score:.1f}): {output_path}")
            return True
    except Exception as e:
        logger.error(f"Frame extraction failed: {e}")
    return False


def build_thumbnail_text_filter(hook_text: str, font_path: str,
                                 thumb_w: int = 1280, thumb_h: int = 720) -> str:
    hook_text = hook_text.strip().upper()
    words = hook_text.split()
    lines = []
    current_line = ""
    for word in words:
        test = (current_line + " " + word).strip()
        if len(test) <= 20:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
        if len(lines) == 2 and current_line:
            lines.append(current_line)
            current_line = ""
            break
    if current_line and len(lines) < 3:
        lines.append(current_line)
    if not lines: return ""

    escaped_font = escape_font_path(font_path)
    font_size = 72
    line_spacing = 85
    start_y = int(thumb_h * 0.72)

    drawtext_filters = []
    for i, line in enumerate(lines):
        y_pos = start_y + (i * line_spacing)
        safe_text = line.replace("'", "\\'").replace(":", "\\:").replace("%", "\\%").replace("\\", "\\\\")
        dt = (
            f"drawtext=fontfile={escaped_font}"
            f":text='{safe_text}'"
            f":fontsize={font_size}"
            f":fontcolor=yellow"
            f":borderw=4:bordercolor=black"
            f":shadowx=3:shadowy=3:shadowcolor=black@0.8"
            f":x=(w-text_w)/2"
            f":y={y_pos}"
        )
        drawtext_filters.append(dt)
    return ",".join(drawtext_filters)


def build_thumbnail_prompt(hook_text: str, transcript_snippet: str = "") -> str:
    base = hook_text.strip() if hook_text else "viral moment"
    prompt = (
        f"cinematic thumbnail for YouTube Shorts, concept: {base}, "
        f"dramatic lighting, high contrast, vivid colors, "
        f"professional photography, 4K, sharp focus, "
        f"no text, no watermark, vertical 9:16 composition"
    )
    if transcript_snippet:
        snippet = transcript_snippet[:100].strip()
        prompt += f", about: {snippet}"
    return prompt


def generate_pollinations_image(prompt: str, output_path: str,
                                 width: int = 720, height: int = 1280,
                                 max_retries: int = 3) -> bool:
    encoded_prompt = quote(prompt.strip())
    url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}&nologo=true&seed={int(time.time())}"
    )
    logger.info(f"Generating Pollinations image: {url[:100]}...")
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=45)
            response.raise_for_status()
            if len(response.content) < 5000:
                raise ValueError(f"Suspicious small response: {len(response.content)} bytes")
            with open(output_path, "wb") as f:
                f.write(response.content)
            logger.info(f"Pollinations image saved: {output_path} ({len(response.content)//1024}KB)")
            return True
        except Exception as e:
            logger.warning(f"Pollinations attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
    logger.error("All Pollinations attempts failed \u2014 using frame fallback")
    return False


def generate_gradient_thumbnail(output_path: str, hook_text: str = "",
                                 width: int = 1080, height: int = 1920) -> bool:
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", (f"gradients=size={width}x{height}:"
               f"x0=0:y0=0:x1={width}:y1={height}:"
               f"c0=0x0A0A0A:c1=0x1A1A2E:c2=0x16213E:nb_colors=3"),
        "-vframes", "1", "-q:v", "2", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        cmd_simple = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x0A0A0A:size={width}x{height}:rate=1",
            "-vframes", "1", output_path,
        ]
        subprocess.run(cmd_simple, capture_output=True)
    logger.info(f"Gradient thumbnail fallback generated: {output_path}")
    return os.path.exists(output_path)


def generate_thumbnail(clip_path: Path, hooks: list = None, transcript: str = ""):
    try:
        dur, vid_w, vid_h = get_video_info(clip_path)
    except Exception:
        return None

    thumb_path = CLIPS_DIR / f"{clip_path.stem}_thumb.jpg"
    ai_image_path = CLIPS_DIR / f"ai_tmp_{clip_path.stem}.jpg"
    fallback_frame_path = CLIPS_DIR / f"frame_tmp_{clip_path.stem}.jpg"

    hook_text = _re.sub(r"[^\w\s\.,!?\-\'\"#@]", "", str(hooks[0])).strip() if hooks else ""
    prompt = build_thumbnail_prompt(hook_text, transcript)

    ai_success = generate_pollinations_image(prompt, str(ai_image_path), width=vid_w, height=vid_h)

    background_source = None
    base_image_filter = f"scale={vid_w}:{vid_h}:flags=lanczos"

    if ai_success:
        background_source = str(ai_image_path)
        logger.info("Using Pollinations AI image as thumbnail background")
    else:
        frame_success = extract_best_thumbnail_frame(str(clip_path), str(fallback_frame_path),
                                                       thumb_w=vid_w, thumb_h=vid_h)
        if frame_success:
            background_source = str(fallback_frame_path)
            logger.info("Using best-scored video frame as thumbnail background")
        else:
            generate_gradient_thumbnail(str(fallback_frame_path), hook_text, width=vid_w, height=vid_h)
            background_source = str(fallback_frame_path)
            logger.warning("Using gradient fallback for thumbnail")

    text_filter = ""
    if hook_text and _THUMB_FONT:
        text_filter = build_thumbnail_text_filter(hook_text, _THUMB_FONT, thumb_w=vid_w, thumb_h=vid_h)

    vf_parts = [base_image_filter]
    if text_filter:
        vf_parts.append(text_filter)

    cmd = [
        "ffmpeg", "-y", "-i", background_source,
        "-vf", ",".join(vf_parts),
        "-frames:v", "1", "-q:v", "2", str(thumb_path),
    ]

    logger.info(f"Compositing thumbnail with FFmpeg: {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=40)
        if r.returncode == 0:
            if ai_image_path.exists(): ai_image_path.unlink()
            if fallback_frame_path.exists(): fallback_frame_path.unlink()
            logger.info(f"\u2713 Thumbnail SUCCESS: {thumb_path.name}")
            return thumb_path
        else:
            err = r.stderr.decode(errors='replace')
            logger.error(f"Thumbnail FFmpeg failed (rc={r.returncode}): {err[-500:]}")
    except Exception as e:
        logger.error(f"Thumbnail composition exception: {e}")

    return None
