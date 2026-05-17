#!/usr/bin/env python3
"""
Voxly – Viral Shorts Backend
Analyzes YouTube videos, finds hook segments, cuts 9:16 clips.
"""
from flask import Flask
from flask_cors import CORS

from config import PORT, logger, BASE_DIR
from utils.db import init_db
from utils.ffmpeg import check_deps
from utils.fonts import resolve_font_path
from pipeline.download import should_update_ytdlp, update_ytdlp_background, get_ytdlp_version

app = Flask(__name__)
CORS(app)

init_db()

from routes import register_routes
register_routes(app)

if __name__ == "__main__":
    logger.info("Voxly - Clipper Backend")
    logger.info(f"     http://localhost:{PORT}")

    missing = check_deps()
    if missing:
        logger.error(f"Missing dependencies: {', '.join(missing)}")
        logger.error("Install them or clips won't generate.")
    else:
        logger.info("ffmpeg, ffprobe, yt-dlp found")

    if should_update_ytdlp():
        update_ytdlp_background()
    else:
        logger.info(f"yt-dlp up to date (v{get_ytdlp_version()})")

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
