import json
import os
import platform
import shutil
import subprocess
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory, Response, stream_with_context

from config import CLIPS_DIR, LOGOS_DIR, UPLOADS_DIR, FONTS_DIR, BASE_DIR, logger
from utils.ffmpeg import get_video_info
from utils.db import _load_words, _save_words, get_db
from pipeline.captions import generate_srt_content, format_ass_time

bp = Blueprint("media", __name__)


@bp.route("/api/upload-logo", methods=["POST"])
def upload_logo():
    if "file" not in request.files:
        return jsonify({"error": "No file field in request"}), 400
    f = request.files["file"]
    if not f.filename: return jsonify({"error": "Empty filename"}), 400
    allowed = {".png", ".jpg", ".jpeg", ".webp"}
    ext = Path(f.filename).suffix.lower()
    if ext not in allowed:
        return jsonify({"error": f"Unsupported format {ext}. Use PNG, JPG or WebP."}), 400
    safe_name = f"logo_{uuid.uuid4().hex[:8]}{ext}"
    dest = LOGOS_DIR / safe_name
    try: f.save(str(dest))
    except Exception as e: return jsonify({"error": f"Save failed: {e}"}), 500
    return jsonify({"ok": True, "filename": safe_name})


@bp.route("/api/upload-video", methods=["POST"])
def upload_video():
    if "file" not in request.files:
        return jsonify({"error": "No file field in request"}), 400
    f = request.files["file"]
    if not f.filename: return jsonify({"error": "Empty filename"}), 400
    allowed = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    ext = Path(f.filename).suffix.lower()
    if ext not in allowed:
        return jsonify({"error": f"Unsupported format {ext}. Use MP4, MOV, MKV, WEBM or AVI."}), 400
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / safe_name
    try: f.save(str(dest))
    except Exception as e: return jsonify({"error": f"Save failed: {e}"}), 500
    try:
        duration, width, height = get_video_info(dest)
        if duration < 5:
            dest.unlink(missing_ok=True)
            return jsonify({"error": "Video is too short (minimum 5 s)."}), 400
    except Exception:
        dest.unlink(missing_ok=True)
        return jsonify({"error": "Could not read video file. Is it a valid video?"}), 400
    return jsonify({"ok": True, "filename": safe_name, "duration": duration, "width": width, "height": height})


@bp.route("/api/upload-font", methods=["POST"])
def upload_font():
    if "file" not in request.files: return jsonify({"error": "No file field"}), 400
    f = request.files["file"]
    if not f.filename: return jsonify({"error": "Empty filename"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in (".ttf", ".otf", ".woff"):
        return jsonify({"error": "Unsupported format. Use TTF or OTF."}), 400
    safe_name = f.filename
    dest = FONTS_DIR / safe_name
    try: f.save(str(dest))
    except Exception as e: return jsonify({"error": f"Save failed: {e}"}), 500
    user_fonts = Path.home() / ".fonts"
    user_fonts.mkdir(exist_ok=True)
    try:
        shutil.copy2(str(dest), str(user_fonts / safe_name))
        if platform.system() != "Windows":
            try: subprocess.run(["fc-cache", "-fv"], capture_output=True, timeout=30)
            except: pass
        logger.info(f"Font installed successfully: {safe_name}")
    except Exception as e: logger.warning(f"Font install warning: {e}")
    font_name = Path(safe_name).stem
    return jsonify({"ok": True, "fontName": font_name, "filename": safe_name})


@bp.route("/api/trim-clip/<filename>")
def trim_clip(filename):
    safe = Path(filename).name
    if not safe.endswith(".mp4"):
        return jsonify({"error": "Invalid file"}), 400
    clip_path = CLIPS_DIR / safe
    if not clip_path.exists(): return jsonify({"error": "Clip not found"}), 404
    try:
        t_start = round(float(request.args.get("start", 0)), 3)
        t_end   = round(float(request.args.get("end", 0)), 3)
    except ValueError: return jsonify({"error": "Invalid time parameters"}), 400
    if t_end <= t_start or t_start < 0: return jsonify({"error": "Invalid trim range"}), 400
    duration = round(t_end - t_start, 3)
    out_path = CLIPS_DIR / f"trim_{uuid.uuid4().hex[:8]}.mp4"
    cmd = ["ffmpeg", "-ss", str(t_start), "-i", str(clip_path), "-t", str(duration),
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-y", str(out_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0: return jsonify({"error": "Trim failed"}), 500
        file_size = out_path.stat().st_size
        def stream_and_cleanup():
            try:
                with open(str(out_path), "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk: break
                        yield chunk
            finally:
                try: out_path.unlink(missing_ok=True)
                except: pass
        return Response(stream_with_context(stream_and_cleanup()), mimetype="video/mp4",
                        headers={"Content-Disposition": f'attachment; filename="trimmed_{safe}"',
                                 "Content-Length": str(file_size), "X-Accel-Buffering": "no"})
    except Exception as e:
        try: out_path.unlink(missing_ok=True)
        except: pass
        return jsonify({"error": str(e)}), 500


@bp.route("/api/clip-srt/<filename>")
def get_clip_srt(filename):
    srt_path = CLIPS_DIR / Path(filename).with_suffix(".srt").name
    if not srt_path.exists():
        mp4_name = Path(filename).with_suffix(".mp4").name
        words = _load_words(mp4_name)
        if not words: return jsonify({"error": "SRT not available for this clip"}), 404
        srt_content = generate_srt_content(words)
        return Response(srt_content, mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{Path(filename).stem}.srt"'})
    return send_from_directory(str(CLIPS_DIR), srt_path.name, mimetype="text/plain; charset=utf-8",
                                as_attachment=True, download_name=Path(filename).stem + ".srt")


@bp.route("/api/clip-transcript/<filename>")
def get_clip_transcript(filename):
    mp4_name = Path(filename).with_suffix(".mp4").name
    words = _load_words(mp4_name)
    if not words: return jsonify({"error": "Transcript not available \u2014 captions may have been disabled."}), 404
    return jsonify({"words": words})


@bp.route("/api/rebake-captions", methods=["POST"])
def rebake_captions():
    data = request.get_json(force=True, silent=True) or {}
    filename = (data.get("filename") or "").strip()
    words = data.get("words") or []
    caption_style = data.get("captionStyle", "mrbeast")
    custom_cfg = data.get("customStyle") or None
    if not filename or not words:
        return jsonify({"error": "filename and words are required"}), 400
    src = CLIPS_DIR / filename
    if not src.exists():
        src = CLIPS_DIR / Path(filename).with_suffix(".mp4").name
        if not src.exists(): return jsonify({"error": "Source clip not found"}), 404
    ext = src.suffix.lower()
    new_name = f"rebaked_{uuid.uuid4().hex[:8]}{ext}"
    out = CLIPS_DIR / new_name
    srt_out = out.with_suffix(".srt")
    ass_path = src.with_suffix(f"_{uuid.uuid4().hex[:4]}.ass")

    STYLE_CONFIGS_REBAKE = {
        "mrbeast": {"font":"Impact","size":110,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H80000000","bold":-1,"outline_w":3,"shadow":2,"marginv":288,"chunk":3,"highlight":"&H0000FFFF","upper":True},
        "hormozi": {"font":"Arial Black","size":105,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&HA0000000","bold":-1,"outline_w":2,"shadow":1,"marginv":240,"chunk":2,"highlight":"&H0014D4FF","upper":True},
        "garyvee": {"font":"Arial Black","size":115,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H90000000","bold":-1,"outline_w":4,"shadow":0,"marginv":260,"chunk":2,"highlight":"&H002165FB","upper":True},
        "loganpaul": {"font":"Poppins","size":100,"primary":"&H00E2E8F0","outline":"&H00000000","back":"&H70000000","bold":-1,"outline_w":2,"shadow":3,"marginv":270,"chunk":3,"highlight":"&H00F8BD38","upper":True},
        "minimal": {"font":"Inter","size":90,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H55000000","bold":0,"outline_w":0,"shadow":2,"marginv":260,"chunk":4,"highlight":"&H00CCCCCC","upper":False},
        "tiktok": {"font":"Arial Black","size":112,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H80000000","bold":-1,"outline_w":3,"shadow":2,"marginv":280,"chunk":2,"highlight":"&H00FF2DD4","upper":True},
        "imangadzi": {"font":"Impact","size":108,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H88000000","bold":-1,"outline_w":3,"shadow":1,"marginv":270,"chunk":2,"highlight":"&H0022B4FF","upper":True},
        "devinjatho": {"font":"Arial Black","size":118,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H75000000","bold":-1,"outline_w":4,"shadow":0,"marginv":265,"chunk":2,"highlight":"&H0040E040","upper":True},
        "karaoke": {"font":"Impact","size":108,"primary":"&H0000FFFF","outline":"&H00000000","back":"&H60000000","bold":-1,"outline_w":3,"shadow":1,"marginv":270,"chunk":4,"highlight":"&H0000FFFF","upper":True,"_karaoke":True},
        "outlined": {"font":"Arial Black","size":106,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H00000000","bold":-1,"outline_w":8,"shadow":0,"marginv":272,"chunk":3,"highlight":"&H0040C0FF","upper":True},
        "gradient": {"font":"Impact","size":108,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H70000000","bold":-1,"outline_w":3,"shadow":1,"marginv":270,"chunk":3,"highlight":"&H0000FFFF","upper":True,"_gradient":True},
    }

    def hex_to_ass_rb(h: str) -> str:
        h = h.lstrip("#")
        if len(h) == 6: r, g, b = h[0:2], h[2:4], h[4:6]; return f"&H00{b}{g}{r}"
        return h

    cfg = dict(STYLE_CONFIGS_REBAKE.get(caption_style, STYLE_CONFIGS_REBAKE["mrbeast"]))
    if custom_cfg:
        if custom_cfg.get("font"): cfg["font"] = custom_cfg["font"]
        if custom_cfg.get("size"): cfg["size"] = int(custom_cfg["size"])
        if custom_cfg.get("primaryColor"): cfg["primary"] = hex_to_ass_rb(custom_cfg["primaryColor"])
        if custom_cfg.get("outlineColor"): cfg["outline"] = hex_to_ass_rb(custom_cfg["outlineColor"])
        if custom_cfg.get("highlightColor"): cfg["highlight"] = hex_to_ass_rb(custom_cfg["highlightColor"])
        if custom_cfg.get("wordsPerLine"): cfg["chunk"] = int(custom_cfg["wordsPerLine"])
        if custom_cfg.get("position") == "top": cfg["marginv"] = 80
        elif custom_cfg.get("position") == "center": cfg["marginv"] = 900

    ass_header = f"""[Script Info]\nScriptType: v4.00+\nCollisions: Normal\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{cfg['font']},{cfg['size']},{cfg['primary']},&H000000FF,{cfg['outline']},{cfg['back']},{cfg['bold']},0,0,0,100,100,0,0,1,{cfg['outline_w']},{cfg['shadow']},2,20,20,{cfg['marginv']},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""

    chunk_size = int(cfg["chunk"])
    upper = bool(cfg["upper"])
    HL_TAG = "{\\c" + cfg["highlight"] + "&}"
    events = []
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        for wi, w in enumerate(chunk):
            t0 = format_ass_time(w.get("start", 0))
            t1 = format_ass_time(chunk[wi+1]["start"] if wi < len(chunk)-1 else w.get("end", w.get("start",0)+1))
            parts = []
            for j, cw in enumerate(chunk):
                if j > wi: break
                txt = cw.get("word","").strip()
                if upper: txt = txt.upper()
                parts.append(f"{HL_TAG}{txt}{{\\r}}" if j == wi else txt)
            events.append(f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{' '.join(parts)}\\N")

    vcodec = "libx264"
    crf_flags = ["-crf", "26"]
    extra_flags = ["-movflags", "+faststart"]
    if ext == ".webm":
        vcodec = "libvpx-vp9"
        crf_flags = ["-b:v", "0", "-crf", "28"]
        extra_flags = []

    try:
        ass_path.write_text(ass_header + "\n".join(events) + "\n", encoding="utf-8")
        escaped_ass = str(ass_path.absolute()).replace("\\", "/").replace(":", "\\:")
        r = subprocess.run(["ffmpeg", "-i", str(src), "-vf", f"ass='{escaped_ass}'",
                             "-c:v", vcodec, "-preset", "ultrafast", *crf_flags,
                             "-c:a", "copy", *extra_flags, "-y", str(out)], capture_output=True)
        if r.returncode != 0:
            return jsonify({"error": "Re-bake failed: " + r.stderr.decode(errors="replace")[-400:]}), 500
        srt_out.write_text(generate_srt_content(words), encoding="utf-8")
        _save_words(new_name, words)
        try:
            r_conn = get_db()
            with r_conn:
                r_conn.execute("UPDATE clips SET filename = ?, file_size = ? WHERE filename = ?",
                               (new_name, out.stat().st_size, src.name))
        except Exception as db_err: logger.error(f"Failed to update rebaked clip in SQLite: {db_err}", exc_info=True)
        return jsonify({"clip": f"/clips/{new_name}", "ok": True})
    except Exception as e: return jsonify({"error": str(e)}), 500
    finally:
        if ass_path.exists():
            try: ass_path.unlink()
            except: pass


@bp.route("/api/alpha-export/<filename>")
def alpha_export(filename):
    mp4_name = Path(filename).with_suffix(".mp4").name
    clip_path = CLIPS_DIR / mp4_name
    ass_path = CLIPS_DIR / (Path(mp4_name).stem + ".ass")
    webm_name = Path(mp4_name).stem + "_alpha.webm"
    webm_path = CLIPS_DIR / webm_name
    if not clip_path.exists(): return jsonify({"error": "Clip not found"}), 404
    if not ass_path.exists(): return jsonify({"error": "Caption file not available"}), 404
    try:
        r_probe = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(clip_path)],
                                  capture_output=True, timeout=10)
        dur = float(json.loads(r_probe.stdout)["format"]["duration"])
    except Exception: dur = 60.0
    escaped_ass = str(ass_path.absolute()).replace("\\", "/").replace(":", "\\:")
    r = subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "color=s=1080x1920:r=30:c=black@0.0", "-t", str(dur),
                         "-vf", f"ass='{escaped_ass}'", "-c:v", "libvpx-vp9",
                         "-b:v", "0", "-crf", "20", "-pix_fmt", "yuva420p",
                         "-auto-alt-ref", "0", "-an", "-y", str(webm_path)], capture_output=True, timeout=180)
    if r.returncode != 0: return jsonify({"error": "Alpha render failed: " + r.stderr.decode(errors="replace")[-500:]}), 500
    return send_from_directory(str(CLIPS_DIR), webm_name, mimetype="video/webm",
                                as_attachment=True, download_name=Path(mp4_name).stem + "_alpha_captions.webm")


@bp.route("/api/translate-srt/<filename>")
def translate_srt(filename):
    mp4_name = Path(filename).with_suffix(".mp4").name
    words = _load_words(mp4_name)
    if not words: return jsonify({"error": "Transcript not available"}), 404
    def srt_t(s: float) -> str:
        h = int(s // 3600); m = int((s % 3600) // 60)
        sec = int(s % 60); ms = int(round((s - int(s)) * 1000))
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
    try:
        from deep_translator import GoogleTranslator
        target_lang = request.args.get("lang", "en").strip().lower()
        translator = GoogleTranslator(source="auto", target=target_lang)
        chunk_size = 6
        srt_parts, idx = [], 1
        for i in range(0, len(words), chunk_size):
            chunk = words[i:i + chunk_size]
            t0 = chunk[0].get("start", 0); t1 = chunk[-1].get("end", t0 + 2)
            text = " ".join(w.get("word", "").strip() for w in chunk if w.get("word", "").strip())
            if not text: continue
            try: translated = translator.translate(text) or text
            except: translated = text
            srt_parts.append(f"{idx}\n{srt_t(t0)} --> {srt_t(t1)}\n{translated}\n")
            idx += 1
        stem = Path(filename).stem
        return Response("\n".join(srt_parts), mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stem}_english.srt"'})
    except ImportError: return jsonify({"error": "Translation library not available. Run: pip install deep-translator"}), 500
    except Exception as e: return jsonify({"error": f"Translation failed: {e}"}), 500


@bp.route("/api/audio-raw/<filename>")
def audio_raw(filename):
    raw_name = Path(filename).stem + "_raw.mp3"
    raw_path = CLIPS_DIR / raw_name
    if not raw_path.exists(): return jsonify({"error": "Raw audio not available"}), 404
    return send_from_directory(str(CLIPS_DIR), raw_name, mimetype="audio/mpeg")


@bp.route("/api/burn-hook/<filename>")
def burn_hook(filename):
    mp4_name = Path(filename).with_suffix(".mp4").name
    clip_path = CLIPS_DIR / mp4_name
    if not clip_path.exists(): return jsonify({"error": "Clip not found"}), 404
    hook_text = request.args.get("text", "").strip()
    if not hook_text: return jsonify({"error": "No hook text provided"}), 400
    out_name = Path(mp4_name).stem + "_hooked.mp4"
    out_path = CLIPS_DIR / out_name
    safe = hook_text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace("%", "\\%")
    vf = (f"drawtext=text='{safe}'"
          f":fontcolor=white:fontsize=52:font=Impact:bold=1"
          f":box=1:boxcolor=black@0.72:boxborderw=18"
          f":x=(w-text_w)/2:y=h*0.055")
    r = subprocess.run(["ffmpeg", "-i", str(clip_path), "-vf", vf,
                         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                         "-c:a", "copy", "-movflags", "+faststart", "-y", str(out_path)],
                        capture_output=True, timeout=120)
    if r.returncode != 0: return jsonify({"error": "Render failed: " + r.stderr.decode(errors="replace")[-500:]}), 500
    return send_from_directory(str(CLIPS_DIR), out_name, mimetype="video/mp4",
                                as_attachment=True, download_name=Path(mp4_name).stem + "_hooked.mp4")


@bp.route("/clips/<path:filename>")
def serve_clip(filename):
    return send_from_directory(str(CLIPS_DIR), filename)
