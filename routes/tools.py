import json
import re as _re
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from config import CLIPS_DIR, COOKIES_FILE, BASE_DIR, YTDLP_LAST_UPDATE_FILE, logger
from utils.ffmpeg import check_deps
from utils.db import _load_words
from pipeline.download import (
    _cookie_ready, get_ytdlp_version, should_update_ytdlp,
    update_ytdlp_background,
)

bp = Blueprint("tools", __name__)


@bp.route("/api/cookies", methods=["POST"])
def upload_cookies():
    data = request.get_json(force=True, silent=True) or {}
    content = data.get("content", "").strip()
    if not content: return jsonify({"error": "No cookie content provided"}), 400
    if "youtube.com" not in content and "google.com" not in content:
        return jsonify({"error": "Does not look like YouTube cookies"}), 400
    try:
        COOKIES_FILE.write_text(content, encoding="utf-8")
        _cookie_ready.set()
        return jsonify({"ok": True, "message": "Cookies saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/cookie-status")
def cookie_status():
    has_cookies = COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 200
    return jsonify({"hasCookies": has_cookies, "ready": _cookie_ready.is_set()})


@bp.route("/api/chapters/<filename>")
def get_chapters(filename):
    mp4_name = Path(filename).with_suffix(".mp4").name
    clip_path = CLIPS_DIR / mp4_name
    if not clip_path.exists(): return jsonify({"error": "Clip not found"}), 404
    try:
        r = subprocess.run(
            ["ffmpeg", "-i", str(clip_path), "-vf", "select=gt(scene\\,0.30),showinfo",
             "-an", "-f", "null", "-"], capture_output=True, timeout=60,
        )
    except Exception as exc: return jsonify({"error": str(exc)}), 500
    stderr = r.stderr.decode(errors="replace")
    scene_times = []
    for line in stderr.splitlines():
        m = _re.search(r"pts_time:(\d+\.?\d*)", line)
        if m:
            t = float(m.group(1))
            if t > 0.3: scene_times.append(round(t, 2))
    deduped = []
    for t in sorted(scene_times):
        if not deduped or t - deduped[-1] >= 1.5:
            deduped.append(t)
    words = _load_words(mp4_name)
    def label_at(t: float) -> str:
        if not words: return "Scene"
        nearby = [w for w in words if abs(float(w.get("start", 0)) - t) <= 2.5]
        return " ".join(w.get("word", "").strip().title() for w in nearby[:4]) if nearby else "Scene"
    chapters = [{"time": 0.0, "label": "Intro"}]
    for t in deduped[:12]:
        chapters.append({"time": t, "label": label_at(t)})
    return jsonify({"chapters": chapters})


@bp.route("/api/video-preview")
def video_preview():
    video_id = request.args.get("v", "").strip()
    if not video_id: return jsonify({"error": "video ID required"}), 400
    has_transcript = False
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        YouTubeTranscriptApi.list_transcripts(video_id)
        has_transcript = True
    except Exception: pass
    thumbnail = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
    meta = {"thumbnail": thumbnail, "hasTranscript": has_transcript}
    try:
        r = subprocess.run(
            ["yt-dlp", "--dump-json", "--skip-download", "--no-playlist",
             "--quiet", f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, timeout=15,
        )
        if r.returncode == 0:
            info = json.loads(r.stdout)
            meta.update({
                "title": info.get("title", ""), "channel": info.get("channel", ""),
                "duration": int(info.get("duration", 0)),
                "views": info.get("view_count", 0),
                "thumbnail": info.get("thumbnail", thumbnail),
            })
    except Exception: pass
    return jsonify(meta)


@bp.route("/health")
def health():
    missing = check_deps()
    from pipeline.transcribe import whisper_model, get_available_vram_mb
    vram_mb = get_available_vram_mb()
    return jsonify({
        "status": "ok" if not missing else "degraded",
        "missing_tools": missing,
        "vram": {"available_mb": vram_mb, "gpu_mode": vram_mb > 0,
                  "whisper_device": getattr(whisper_model, "device", "not_loaded") if whisper_model else "not_loaded"},
        "ytdlp": {
            "version": get_ytdlp_version(),
            "last_updated": YTDLP_LAST_UPDATE_FILE.read_text().strip() if YTDLP_LAST_UPDATE_FILE.exists() else "never",
            "update_due": should_update_ytdlp(),
        },
    })


@bp.route("/api/update-ytdlp", methods=["POST"])
def trigger_ytdlp_update():
    update_ytdlp_background()
    return jsonify({"message": "yt-dlp update started in background", "current_version": get_ytdlp_version()})


@bp.route("/")
def root():
    return send_from_directory(str(BASE_DIR), "index.html")


@bp.route("/<path:filename>")
def serve_static(filename):
    if filename in ("app.js", "style.css"):
        return send_from_directory(str(BASE_DIR), filename)
    return jsonify({"error": "File not found"}), 404
