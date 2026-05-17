import uuid
from pathlib import Path
import subprocess

from config import CLIPS_DIR, logger


def _build_broll_prompt(segment_text: str) -> str:
    snippet = ' '.join(segment_text.split()[:10]).strip('.,!?;:')
    return (
        f"cinematic vertical 9:16 B-roll footage, {snippet}, "
        "4K quality, dramatic lighting, bokeh, no faces, "
        "no text, no watermarks, photorealistic, professional photography"
    )


def extract_broll_moments(words: list, clip_duration: float, max_brolls: int = 3) -> list:
    if clip_duration < 8: return []

    if not words:
        moments = []
        slot_dur = min(4.0, clip_duration * 0.25)
        step = clip_duration / (max_brolls + 1)
        for k in range(1, max_brolls + 1):
            t = round(step * k, 2)
            if t + slot_dur < clip_duration - 1.0:
                moments.append({
                    'start': round(t, 2), 'duration': round(slot_dur, 2),
                    'prompt': 'cinematic vertical 9:16 B-roll, dramatic lighting, bokeh, no faces, no text, photorealistic',
                })
        return moments

    segs = []
    seg_start = words[0].get('start', 0)
    seg_words = []
    for w in words:
        seg_words.append(w.get('word', ''))
        t_end = w.get('end', 0)
        if t_end - seg_start >= 6.0:
            segs.append((seg_start, t_end, ' '.join(seg_words)))
            seg_start = t_end
            seg_words = []
    if seg_words:
        t_end = words[-1].get('end', 0)
        segs.append((seg_start, t_end, ' '.join(seg_words)))

    moments = []
    for seg_start, seg_end, text in segs:
        if seg_start < 1.0 or seg_end > clip_duration - 1.0: continue
        seg_len = seg_end - seg_start
        if seg_len < 3.5: continue
        moments.append({
            'start': round(seg_start + 0.2, 2),
            'duration': round(min(5.0, seg_len * 0.6), 2),
            'prompt': _build_broll_prompt(text),
        })
        if len(moments) >= max_brolls: break
    return moments


def download_broll_image(prompt: str, idx: int):
    import urllib.request as ureq
    import urllib.parse
    import random
    encoded = urllib.parse.quote(prompt, safe='')
    seed = random.randint(1000, 99999)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=540&height=960&nologo=true&seed={seed}"
    )
    out_path = CLIPS_DIR / f"broll_img_{uuid.uuid4().hex[:8]}.jpg"
    for attempt in range(2):
        try:
            logger.info(f"BRoll: Fetching image {idx+1} (attempt {attempt+1}): {prompt[:60]}...")
            req = ureq.Request(url, headers={'User-Agent': 'Voxly/1.0'})
            with ureq.urlopen(req, timeout=55) as resp:
                data = resp.read()
            if len(data) < 2000:
                logger.warning(f"BRoll: Image {idx+1} too small ({len(data)} bytes) \u2014 skipping")
                return None
            out_path.write_bytes(data)
            logger.info(f"BRoll: Downloaded image {idx+1} ({len(data)//1024} KB)")
            return out_path
        except Exception as e:
            logger.warning(f"BRoll: Image download attempt {attempt+1} failed (idx={idx}): {e}")
    return None


def image_to_video(image_path: Path, duration: float, output_path: Path,
                    out_w: int = 1080, out_h: int = 1920) -> bool:
    cmd = [
        'ffmpeg', '-loop', '1', '-i', str(image_path),
        '-vf', (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},fps=30"
        ),
        '-t', str(duration),
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
        '-pix_fmt', 'yuv420p', '-an',
        '-y', str(output_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception as e:
        logger.error("BRoll: image_to_video failed", exc_info=True)
        return False


def apply_brolls_to_clip(main_clip: Path, brolls: list, output: Path,
                          out_w: int = 1080, out_h: int = 1920,
                          out_vcodec: str = "libx264",
                          out_extra_flags: list = None) -> bool:
    if out_extra_flags is None: out_extra_flags = ["-movflags", "+faststart"]
    if not brolls: return False
    n = len(brolls)
    cmd = ['ffmpeg', '-i', str(main_clip)]
    for b in brolls:
        cmd += ['-i', b['video_path']]

    filter_parts = []
    for i, b in enumerate(brolls):
        filter_parts.append(
            f"[{i+1}:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},setsar=1,format=yuv420p[bv{i}]"
        )

    prev = "[0:v]"
    for i, b in enumerate(brolls):
        s = round(b['start'], 3)
        e = round(b['start'] + b['duration'], 3)
        out_label = f"[ov{i}]" if i < n - 1 else "[vout]"
        filter_parts.append(
            f"{prev}[bv{i}]overlay="
            f"x='if(between(t,{s},{e}),0,9999)':y=0:shortest=1{out_label}"
        )
        prev = f"[ov{i}]"

    cmd += [
        '-filter_complex', ';'.join(filter_parts),
        '-map', '[vout]', '-map', '0:a',
        '-c:v', out_vcodec, '-preset', 'ultrafast', '-crf', '26',
        '-c:a', 'copy', *out_extra_flags,
        '-y', str(output),
    ]
    logger.info(f"BRoll: Running apply_brolls FFmpeg ({n} B-rolls)...")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        if r.returncode != 0:
            err = r.stderr.decode(errors='replace')
            logger.error(f"BRoll: apply failed (rc={r.returncode}): {err[-600:]}")
        else:
            logger.info(f"BRoll: apply_brolls succeeded to {output.name}")
        return r.returncode == 0
    except Exception as e:
        logger.error("BRoll: apply exception occurred", exc_info=True)
        return False
