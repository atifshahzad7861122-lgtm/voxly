from flask import Blueprint, jsonify, request

from config import logger
from utils.db import get_db

bp = Blueprint("history", __name__)


@bp.route("/api/history", methods=["GET"])
def api_get_history():
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 10, type=int)
    if page < 1: page = 1
    if limit < 1: limit = 10
    offset = (page - 1) * limit

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM clips")
        total = cursor.fetchone()[0]
        pages = (total + limit - 1) // limit if total > 0 else 1
        cursor.execute("""
            SELECT id, filename, source_url, source_type, duration, resolution, format, style, viral_score, file_size, created_at
            FROM clips ORDER BY created_at DESC LIMIT ? OFFSET ?
        """, (limit, offset))
        rows = cursor.fetchall()
        clips = []
        for r in rows:
            clips.append({
                "id": r["id"], "filename": r["filename"], "source_url": r["source_url"],
                "source_type": r["source_type"], "duration": r["duration"],
                "resolution": r["resolution"], "format": r["format"], "style": r["style"],
                "viral_score": r["viral_score"], "file_size": r["file_size"],
                "created_at": r["created_at"],
            })
        return jsonify({"clips": clips, "total": total, "page": page, "pages": pages})
    except Exception as e:
        logger.error(f"Error fetching history: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch history"}), 500
    finally:
        conn.close()


@bp.route("/api/stats", methods=["GET"])
def api_get_stats():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT source_url) FROM clips")
        videos = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM clips")
        clips = cursor.fetchone()[0]
        cursor.execute("SELECT AVG(viral_score) FROM clips")
        avg_score = cursor.fetchone()[0]
        avg_score = round(avg_score, 1) if avg_score is not None else 0.0
        hours = round(clips * 0.5, 1)
        return jsonify({"videos": videos, "clips": clips, "average_viral_score": avg_score, "hours": hours})
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {e}", exc_info=True)
        return jsonify({"error": "Failed to compile dashboard stats"}), 500
    finally:
        conn.close()


@bp.route("/api/history/<int:clip_id>", methods=["DELETE"])
def api_delete_clip(clip_id):
    conn = get_db()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
            rows_affected = cursor.rowcount
        if rows_affected == 0:
            return jsonify({"error": "Clip record not found"}), 404
        return jsonify({"ok": True, "message": "Clip record removed from database"})
    except Exception as e:
        logger.error(f"Error deleting clip record {clip_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to delete clip record"}), 500
    finally:
        conn.close()


@bp.route("/api/history", methods=["DELETE"])
def api_clear_history():
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM clips")
            conn.execute("DELETE FROM sessions")
        return jsonify({"ok": True, "message": "All database history cleared"})
    except Exception as e:
        logger.error(f"Error clearing history: {e}", exc_info=True)
        return jsonify({"error": "Failed to clear history"}), 500
    finally:
        conn.close()
