import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Blueprint, jsonify, request, Response, stream_with_context

from config import (
    PORT, MAX_CLIPS, DEFAULT_DURATION, MIN_GAP_SECONDS, SAMPLE_RATE, ENERGY_WINDOW,
    BASE_DIR, CLIPS_DIR, DOWNLOADS_DIR, UPLOADS_DIR, FONTS_DIR, LOGOS_DIR,
    BUNDLED_FONT_DIR, DB_PATH, COOKIES_FILE, COOKIE_REFRESH_SEC,
    YTDLP_LAST_UPDATE_FILE, YTDLP_UPDATE_INTERVAL_DAYS,
    RESOLUTION_MAP, DEFAULT_RESOLUTION, PRESET_MAP, FORMAT_MAP, DEFAULT_FORMAT,
    COLOR_GRADE_FILTERS, EMOJI_MAP, WHISPER_LANG_PROMPTS, LANGUAGE_CODES,
    WHISPER_VRAM_REQUIREMENTS, WHISPER_MODEL_SIZE, CHROMIUM_PROFILES,
    HOOK_KEYWORDS, logger,
)
from utils.ffmpeg import get_video_info, verify_download_quality
from utils.db import get_db, _load_words
from pipeline.download import download_video
from pipeline.segments import find_speech_dense_segments, _extract_video_id
from pipeline.encode import cut_clip, enforce_quality_floor
from pipeline.broll import extract_broll_moments, download_broll_image, image_to_video, apply_brolls_to_clip
from pipeline.hooks import generate_viral_hooks, calculate_viral_score
from thumbnail.generator import generate_thumbnail

bp = Blueprint("process", __name__)


@bp.route("/api/process", methods=["POST"])
def process():
    data        = request.get_json(force=True, silent=True) or {}
    youtube_url = (data.get("youtubeUrl") or "").strip()
    groq_key    = (data.get("groqKey") or os.environ.get("GROQ_API_KEY") or "").strip()

    source_type   = data.get("sourceType", "youtube")
    upload_file   = (data.get("uploadFile") or "").strip()

    if source_type == "youtube" and not youtube_url:
        return jsonify({"error": "youtubeUrl is required"}), 400
    if source_type == "upload" and not upload_file:
        return jsonify({"error": "uploadFile is required for file source"}), 400

    n_clips = min(int(data.get("clips", MAX_CLIPS)), MAX_CLIPS)
    clip_duration     = int(data.get("duration", DEFAULT_DURATION))
    captions_enabled  = bool(data.get("captions", True))
    caption_style     = data.get("captionStyle", "mrbeast").strip()
    mode              = data.get("mode", "fill").strip().lower()
    lang_name         = (data.get("language") or "english").strip().lower()
    language          = LANGUAGE_CODES.get(lang_name, "en")
    audio_enhance     = bool(data.get("audioEnhance", False))
    custom_style_cfg  = data.get("customStyle") or None
    broll_enabled     = bool(data.get("brollEnabled", False))
    color_grade       = (data.get("colorGrade") or "none").strip()
    auto_zoom         = bool(data.get("autoZoom", False))
    emoji_burst       = bool(data.get("emojiBurst", False))
    logo_config       = data.get("logoConfig") or None
    face_focus        = bool(data.get("faceFocus", False))
    speed_ramp        = bool(data.get("speedRamp", False))

    logger.info("=" * 60)
    logger.info(f"PIPELINE START | source={source_type} | clips={n_clips}")
    logger.info("=" * 60)

    resolution_key = data.get("resolution", DEFAULT_RESOLUTION).lower()
    if resolution_key not in RESOLUTION_MAP:
        logger.warning(f"Unknown resolution '{resolution_key}' \u2014 falling back to {DEFAULT_RESOLUTION}")
        resolution_key = DEFAULT_RESOLUTION
    res_cfg = RESOLUTION_MAP[resolution_key]
    out_width, out_height = res_cfg["width"], res_cfg["height"]
    out_bitrate, out_crf = res_cfg["bitrate"], res_cfg["crf"]

    format_key = data.get("export_format", DEFAULT_FORMAT).lower()
    if format_key not in FORMAT_MAP:
        logger.warning(f"Unknown format '{format_key}' \u2014 falling back to {DEFAULT_FORMAT}")
        format_key = DEFAULT_FORMAT
    fmt_cfg = FORMAT_MAP[format_key]
    out_extension = fmt_cfg["extension"]
    out_vcodec, out_acodec = fmt_cfg["vcodec"], fmt_cfg["acodec"]
    out_pix_fmt = fmt_cfg["pixel_fmt"]
    out_extra_flags = fmt_cfg["extra_flags"]
    out_mime_type = fmt_cfg["mime_type"]

    if resolution_key == "4k":
        logger.warning("4K rendering selected \u2014 this will be slow on CPU")

    if mode not in ("fill", "pad"):
        mode = "fill"

    video_id = _extract_video_id(youtube_url) if youtube_url else None

    def generate():
        video_path = None
        try:
            if source_type == "upload":
                up_path = UPLOADS_DIR / upload_file
                if not up_path.exists():
                    yield json.dumps({"error": "Uploaded file not found. Please re-upload."}) + "\n"
                    return
                video_path = up_path
            else:
                video_path = download_video(youtube_url)

            quality_info = verify_download_quality(video_path)
            source_height = int(quality_info.get("height", 1080) if isinstance(quality_info.get("height"), int) else 1080)

            nonlocal resolution_key, res_cfg, out_width, out_height, out_bitrate, out_crf
            resolution_key = enforce_quality_floor(source_height, resolution_key)
            res_cfg = RESOLUTION_MAP[resolution_key]
            out_width, out_height = res_cfg["width"], res_cfg["height"]
            out_bitrate, out_crf = res_cfg["bitrate"], res_cfg["crf"]
            out_maxrate = res_cfg.get("maxrate", out_bitrate)
            out_bufsize = res_cfg.get("bufsize", "16000k")
            out_preset = PRESET_MAP.get(resolution_key, "medium")

            duration, width, height = get_video_info(video_path)
            if duration < 20:
                yield json.dumps({"error": "Video too short (minimum 20 s)."}) + "\n"; return
            if width == 0 or height == 0:
                yield json.dumps({"error": "Could not read video dimensions."}) + "\n"; return

            segments = find_speech_dense_segments(video_path, duration, n_clips=n_clips,
                                                   clip_duration=clip_duration, video_id=video_id, language=language)
            if not segments:
                yield json.dumps({"error": "No viable segments found."}) + "\n"; return

            yield json.dumps({"total": len(segments)}) + "\n"

            try:
                conn = get_db()
                with conn:
                    conn.execute("INSERT INTO sessions (source_url, total_clips, source_title) VALUES (?, ?, ?)",
                                 (youtube_url or upload_file, len(segments), youtube_url or upload_file))
                logger.info(f"Database session logged: url={youtube_url or upload_file}, clips={len(segments)}")
            except Exception as db_err:
                logger.error(f"Failed to log session to SQLite: {db_err}", exc_info=True)

            def _cut_clip_safe(args):
                i, s, e = args
                try:
                    clip_path, transcript = cut_clip(
                        video_path, s, e, i, width, height, clip_duration,
                        mode, captions_enabled, caption_style,
                        language=language, audio_enhance=audio_enhance,
                        custom_style_cfg=custom_style_cfg,
                        color_grade=color_grade, auto_zoom=auto_zoom,
                        emoji_burst=emoji_burst, logo_config=logo_config,
                        face_focus=face_focus, speed_ramp=speed_ramp,
                        out_width=out_width, out_height=out_height,
                        out_crf=out_crf, out_bitrate=out_bitrate, out_vcodec=out_vcodec,
                        out_acodec=out_acodec, out_pix_fmt=out_pix_fmt,
                        out_extra_flags=out_extra_flags, out_extension=out_extension,
                        out_preset=out_preset, out_maxrate=out_maxrate, out_bufsize=out_bufsize,
                        two_pass=(resolution_key == "1080p"))
                    hooks = []
                    if groq_key and transcript:
                        hooks = generate_viral_hooks(transcript, groq_key)

                    broll_count = 0
                    if broll_enabled:
                        dur = round(e - s, 2)
                        words_for_broll = _load_words(clip_path.name)
                        moments = extract_broll_moments(words_for_broll, dur)
                        logger.info(f"BRoll: Clip {i+1}: dur={dur}s, words={len(words_for_broll)}, moments={len(moments)}")
                        if moments:
                            broll_videos = []
                            def _fetch_and_encode(bi_m):
                                bi, m = bi_m
                                img = download_broll_image(m['prompt'], bi)
                                if not img: return None
                                vid = img.with_suffix('.mp4')
                                ok = image_to_video(img, m['duration'], vid, out_w=out_width, out_h=out_height)
                                try: img.unlink(missing_ok=True)
                                except: pass
                                if ok:
                                    return {'start': m['start'], 'duration': m['duration'], 'video_path': str(vid)}
                                return None
                            with ThreadPoolExecutor(max_workers=min(len(moments), 3)) as bpool:
                                for result in bpool.map(_fetch_and_encode, enumerate(moments)):
                                    if result: broll_videos.append(result)
                            if broll_videos:
                                brtmp = CLIPS_DIR / f"brtmp_{uuid.uuid4().hex[:6]}.mp4"
                                if apply_brolls_to_clip(clip_path, broll_videos, brtmp,
                                                         out_w=out_width, out_h=out_height,
                                                         out_vcodec=out_vcodec, out_extra_flags=out_extra_flags):
                                    try:
                                        brtmp.replace(clip_path)
                                        broll_count = len(broll_videos)
                                    except: brtmp.unlink(missing_ok=True)
                                else:
                                    try: brtmp.unlink(missing_ok=True)
                                    except: pass
                                for bv in broll_videos:
                                    try: Path(bv['video_path']).unlink(missing_ok=True)
                                    except: pass

                    viral_score = calculate_viral_score(transcript, round(e - s, 2), caption_style, broll_count)
                    has_raw = (CLIPS_DIR / f"{clip_path.stem}_raw.mp3").exists()
                    has_ass = (CLIPS_DIR / f"{clip_path.stem}.ass").exists()
                    return {
                        "success": True, "index": i, "path": clip_path,
                        "hooks": hooks, "has_raw": has_raw, "has_ass": has_ass,
                        "viral_score": viral_score, "broll_count": broll_count,
                        "transcript": transcript or "", "error": None,
                    }
                except Exception as ex:
                    logger.error(f"Clip {i} generation failed: {ex}", exc_info=True)
                    return {"success": False, "index": i, "path": None, "error": str(ex)}

            thumb_jobs = {}

            with ThreadPoolExecutor(max_workers=min(max(1, os.cpu_count()), 2)) as pool:
                futures = {pool.submit(_cut_clip_safe, (i, s, e)): i for i, (s, e) in enumerate(segments)}
                for future in as_completed(futures):
                    result = future.result()
                    if result["success"]:
                        clip_path = result["path"]
                        has_srt = clip_path.with_suffix(".srt").exists()
                        has_thumb = (CLIPS_DIR / f"{clip_path.stem}_thumb.jpg").exists()
                        yield json.dumps({
                            "type": "clip_ready", "clip": f"/clips/{clip_path.name}",
                            "index": result["index"], "hooks": result["hooks"],
                            "hasSrt": has_srt, "hasRawAudio": result["has_raw"],
                            "hasAlpha": result["has_ass"], "viralScore": result["viral_score"],
                            "brollCount": result["broll_count"], "hasThumbnail": has_thumb,
                        }) + "\n"

                        try:
                            c_conn = get_db()
                            with c_conn:
                                c_conn.execute("""
                                    INSERT INTO clips (filename, source_url, source_type, duration, resolution, format, style, viral_score, file_size)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (clip_path.name, youtube_url or upload_file, source_type,
                                      round(segments[result["index"]][1] - segments[result["index"]][0], 2)
                                      if result["index"] < len(segments) else 0.0,
                                      resolution_key, format_key, caption_style,
                                      result["viral_score"], clip_path.stat().st_size))
                            logger.info(f"Database clip logged: file={clip_path.name}, score={result['viral_score']}")
                        except Exception as db_err:
                            logger.error(f"Failed to log clip to SQLite: {db_err}", exc_info=True)

                        thumb_jobs[result["index"]] = (clip_path, result["hooks"], result["transcript"])
                    else:
                        yield json.dumps({"type": "clip_error", "index": result["index"],
                                           "error": result["error"], "message": f"Clip {result['index'] + 1} failed: {result['error']}"}) + "\n"

            if thumb_jobs:
                logger.info(f"Phase 2: Generating {len(thumb_jobs)} thumbnails in background...")
                with ThreadPoolExecutor(max_workers=3) as tpool:
                    tfutures = {tpool.submit(generate_thumbnail, cp, h, tr): idx for idx, (cp, h, tr) in thumb_jobs.items()}
                    for tf in as_completed(tfutures):
                        idx = tfutures[tf]
                        try:
                            if tf.result():
                                yield json.dumps({"thumbReady": True, "index": idx}) + "\n"
                        except Exception as te:
                            logger.error(f"Phase 2 yield failed for clip {idx}: {te}")

        except Exception as exc:
            yield json.dumps({"error": str(exc)}) + "\n"
        finally:
            if source_type == "youtube" and video_path and video_path.exists():
                try: video_path.unlink()
                except OSError: pass

    return Response(stream_with_context(generate()),
                     mimetype="application/x-ndjson",
                     headers={"X-Accel-Buffering": "no"})
