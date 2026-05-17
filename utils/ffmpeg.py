import json
import math
import os
import platform
import struct
import subprocess
from pathlib import Path

from config import SAMPLE_RATE, ENERGY_WINDOW, logger


def get_video_info(video_path: Path):
    """Return (duration, width, height) via ffprobe JSON."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(video_path)],
        capture_output=True,
    )
    data = json.loads(r.stdout)
    duration = float(data["format"]["duration"])
    width = height = 0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            width = int(s["width"])
            height = int(s["height"])
            break
    return duration, width, height


def verify_download_quality(video_path: str) -> dict:
    """Log the actual downloaded video quality for debugging."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = stream.get("width", "?")
                h = stream.get("height", "?")
                fps_raw = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = fps_raw.split("/")
                    fps = round(float(num) / float(den), 2)
                except Exception:
                    fps = fps_raw
                logger.info(
                    f"Downloaded video: {w}x{h} @ {fps}fps "
                    f"| codec: {stream.get('codec_name')} "
                    f"| bitrate: {stream.get('bit_rate', 'unknown')}bps"
                )
                return {"width": w, "height": h, "fps": fps}
    except Exception as e:
        logger.warning(f"Quality verification failed: {e}")
    return {}


def check_deps():
    missing = []
    for tool, flag in [("ffmpeg", "-version"), ("ffprobe", "-version"), ("yt-dlp", "--version")]:
        r = subprocess.run([tool, flag], capture_output=True)
        if r.returncode not in (0, 1):
            missing.append(tool)
    return missing


def extract_audio_energy(video_path: Path, duration: float):
    """
    Pipe raw mono 8kHz PCM from FFmpeg and compute per-second RMS energy.
    Returns list of (time_sec, rms) tuples.
    """
    proc = subprocess.Popen(
        [
            "ffmpeg", "-i", str(video_path),
            "-vn", "-ar", str(SAMPLE_RATE), "-ac", "1",
            "-f", "s16le", "pipe:1",
            "-loglevel", "quiet",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    raw, _ = proc.communicate()

    if not raw:
        return [(t, 1.0) for t in range(int(duration))]

    n = len(raw) // 2
    samples = struct.unpack(f"<{n}h", raw)

    win = SAMPLE_RATE * ENERGY_WINDOW
    step = SAMPLE_RATE
    result = []

    for i in range(0, n - win, step):
        chunk = samples[i: i + win: 8]
        if not chunk:
            continue
        rms = math.sqrt(sum(int(s) * int(s) for s in chunk) / len(chunk))
        result.append((i / SAMPLE_RATE, rms))

    return result
