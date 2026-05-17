import json
import sqlite3
from pathlib import Path
from threading import Lock

from config import CLIPS_DIR, DB_PATH, logger


_transcripts: dict = {}
_transcripts_lock = Lock()


def _words_json_path(clip_name: str) -> Path:
    return CLIPS_DIR / (Path(clip_name).stem + ".words.json")


def _save_words(clip_name: str, words: list) -> None:
    with _transcripts_lock:
        _transcripts[clip_name] = words
    try:
        _words_json_path(clip_name).write_text(
            json.dumps(words, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        logger.error(f"Could not save words.json for {clip_name}: {exc}")


def _load_words(clip_name: str) -> list:
    with _transcripts_lock:
        words = _transcripts.get(clip_name)
    if words:
        return words
    jp = _words_json_path(clip_name)
    if jp.exists():
        try:
            words = json.loads(jp.read_text(encoding="utf-8"))
            with _transcripts_lock:
                _transcripts[clip_name] = words
            return words
        except Exception as exc:
            logger.error(f"Could not load words.json for {clip_name}: {exc}")
    return []


def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS clips (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename    TEXT NOT NULL,
                    source_url  TEXT,
                    source_type TEXT DEFAULT 'youtube',
                    duration    REAL,
                    resolution  TEXT DEFAULT '1080p',
                    format      TEXT DEFAULT 'mp4',
                    style       TEXT DEFAULT 'mrbeast',
                    viral_score REAL,
                    file_size   INTEGER,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url   TEXT,
                    total_clips  INTEGER DEFAULT 0,
                    source_title TEXT,
                    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
        logger.info(f"SQLite database initialized at: {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
    finally:
        conn.close()
