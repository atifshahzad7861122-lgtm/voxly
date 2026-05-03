#!/usr/bin/env python3
"""
Voxly – Viral Shorts Backend
Analyzes YouTube videos, finds hook segments, cuts 9:16 clips.

Requirements: pip install flask flask-cors yt-dlp
System deps:  ffmpeg (must be in PATH)
"""

import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS

# ── Config ────────────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 5000))

MAX_CLIPS        = 10      # max clips to generate per video
DEFAULT_DURATION = 45      # default clip seconds if omitted
MIN_GAP_SECONDS  = 60      # minimum spacing between clip start times
SAMPLE_RATE      = 8000    # Hz for audio energy extraction (low = fast)
ENERGY_WINDOW    = 5       # smoothing window in seconds

BASE_DIR      = Path(__file__).parent.resolve()
CLIPS_DIR     = BASE_DIR / "clips"
DOWNLOADS_DIR = BASE_DIR / "downloads"
UPLOADS_DIR  = BASE_DIR / "uploads"
FONTS_DIR     = BASE_DIR / "fonts"
CLIPS_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)
LOGOS_DIR = BASE_DIR / "logos"
LOGOS_DIR.mkdir(exist_ok=True)

# ── Color Grade Presets (pure ffmpeg filter chains) ────────────────────────────
COLOR_GRADE_FILTERS: dict[str, str] = {
    "none":      "",
    "cinematic": (
        "curves=r='0/0 0.5/0.55 1/0.97':g='0/0 0.5/0.48 1/0.95':b='0/0.04 0.5/0.38 1/0.82',"
        "eq=saturation=1.2:contrast=1.05"
    ),
    "warm":   "curves=r='0/0.04 1/1':g='0/0 1/0.97':b='0/0 1/0.82',eq=saturation=1.1:brightness=0.02",
    "cold":   "curves=r='0/0 1/0.86':g='0/0 1/0.96':b='0/0.04 1/1',eq=saturation=0.95",
    "moody":  "eq=contrast=1.2:saturation=0.72:brightness=-0.04,curves=r='0/0.02 1/0.95':b='0/0.02 1/0.92'",
    "bleach": "eq=contrast=1.3:saturation=0.35:brightness=-0.02",
}

# ── Emoji Keyword → (overlay label, box color) ────────────────────────────────
EMOJI_MAP: dict[str, tuple[str, str]] = {
    "insane":       ("INSANE!",       "red@0.82"),
    "crazy":        ("CRAZY!",        "red@0.82"),
    "unbelievable": ("UNBELIEVABLE!", "red@0.82"),
    "shocking":     ("SHOCKING!",     "red@0.82"),
    "money":        ("MONEY!",        "0xE0760A@0.85"),
    "rich":         ("RICH!",         "0xE0760A@0.85"),
    "million":      ("MILLIONS!",     "0xE0760A@0.85"),
    "billion":      ("BILLIONS!",     "0xE0760A@0.85"),
    "win":          ("WIN!",          "0x16A34A@0.85"),
    "won":          ("WE WON!",       "0x16A34A@0.85"),
    "secret":       ("SECRET!",       "0x7C3AED@0.85"),
    "revealed":     ("REVEALED!",     "0x7C3AED@0.85"),
    "truth":        ("THE TRUTH!",    "0x7C3AED@0.85"),
    "amazing":      ("AMAZING!",      "0xB45309@0.85"),
    "incredible":   ("INCREDIBLE!",   "0xB45309@0.85"),
    "stop":         ("STOP!",         "red@0.85"),
    "warning":      ("WARNING!",      "red@0.85"),
    "free":         ("FREE!",         "0x16A34A@0.85"),
    "hack":         ("LIFE HACK!",    "0x0369A1@0.85"),
    "trick":        ("PRO TRICK!",    "0x0369A1@0.85"),
}

# ── Per-language initial prompts to guide Whisper spelling accuracy ──────────
# Written in each language's native script so the model's vocab is anchored correctly.
WHISPER_LANG_PROMPTS: dict[str, str] = {
    "ur": (
        "یہ اردو تقریر ہے۔ تمام الفاظ درست اردو رسم الخط اور صحیح ہجّے کے ساتھ لکھیں۔ "
        "عبادت، توحید، نماز، تہجد، رزق، دعا، صبر، شکر، اللہ، قرآن، حدیث، "
        "مسجد، امام، خطبہ، جمعہ، روزہ، زکات، حج۔"
    ),
    "hi": (
        "यह हिंदी भाषण है। सभी शब्दों को सही हिंदी वर्तनी और व्याकरण के साथ लिखें। "
        "नमाज़, इबादत, तहज्जुद, रोज़ी, दुआ, सब्र, शुक्र, अल्लाह, क़ुरआन, "
        "मस्जिद, इमाम, जुमा, रोज़ा, ज़कात, हज।"
    ),
    "en": (
        "This is a clear English speech. Write all words with correct spelling, "
        "punctuation, and grammar. Use standard English vocabulary."
    ),
    "ar": (
        "هذا خطاب عربي فصيح. اكتب جميع الكلمات بالإملاء العربي الصحيح والنحو السليم. "
        "العبادة، التوحيد، الصلاة، الزكاة، الحج، الدعاء، الصبر، الشكر، القرآن الكريم."
    ),
    "pa": (
        "ਇਹ ਪੰਜਾਬੀ ਭਾਸ਼ਣ ਹੈ। ਸਾਰੇ ਸ਼ਬਦਾਂ ਨੂੰ ਸਹੀ ਪੰਜਾਬੀ ਵਰਤਨੀ ਅਤੇ ਵਿਆਕਰਨ ਨਾਲ ਲਿਖੋ। "
        "ਪਰਮਾਤਮਾ, ਸਤਿਗੁਰੂ, ਗੁਰਬਾਣੀ, ਗੁਰਦੁਆਰਾ, ਨਾਮ, ਸਿਮਰਨ।"
    ),
    "ne": (
        "यो नेपाली भाषण हो। सबै शब्दहरू सही नेपाली वर्तनी र व्याकरणसहित लेख्नुहोस्। "
        "नमस्कार, धन्यवाद, ईश्वर, प्रार्थना, मन्दिर, पूजा।"
    ),
    "te": (
        "ఇది తెలుగు ప్రసంగం. అన్ని పదాలను సరైన తెలుగు వ్యాకరణంతో రాయండి. "
        "నమస్కారం, దేవుడు, దేవాలయం, ప్రార్థన, ధన్యవాదాలు."
    ),
    "ta": (
        "இது தமிழ் பேச்சு. அனைத்து சொற்களையும் சரியான தமிழ் இலக்கணத்துடன் எழுதுங்கள். "
        "வணக்கம், கடவுள், கோவில், பிரார்த்தனை, நன்றி."
    ),
    "bn": (
        "এটি বাংলা ভাষণ। সমস্ত শব্দ সঠিক বাংলা বানান ও ব্যাকরণ সহ লিখুন। "
        "নমস্কার, ঈশ্বর, মন্দির, প্রার্থনা, ধন্যবাদ, ইবাদত।"
    ),
    "gu": (
        "આ ગુજરાતી ભાષણ છે। તમામ શબ્દો સાચી ગુજરાતી જોડણી અને વ્યાકરણ સાથે લખો। "
        "નમસ્કાર, ઈશ્વર, મંદિર, પ્રાર્થના, ખુદા, ઈબાદત."
    ),
    "mr": (
        "हे मराठी भाषण आहे. सर्व शब्द योग्य मराठी शब्दलेखन आणि व्याकरणासह लिहा. "
        "नमस्कार, देव, मंदिर, प्रार्थना, धन्यवाद, इबादत."
    ),
    "ml": (
        "ഇത് മലയാളം പ്രഭാഷണമാണ്. എല്ലാ വാക്കുകളും ശരിയായ മലയാളം വ്യാകരണത്തോടും "
        "അക്ഷരതെറ്റുകൾ ഇല്ലാതെ എഴുതുക. നമസ്കാരം, ദൈവം, ക്ഷേത്രം, പ്രാർത്ഥന."
    ),
    "kn": (
        "ಇದು ಕನ್ನಡ ಭಾಷಣ. ಎಲ್ಲಾ ಪದಗಳನ್ನು ಸರಿಯಾದ ಕನ್ನಡ ವ್ಯಾಕರಣ ಮತ್ತು ಕಾಗುಣಿತದೊಂದಿಗೆ "
        "ಬರೆಯಿರಿ. ನಮಸ್ಕಾರ, ದೇವರು, ದೇವಾಲಯ, ಪ್ರಾರ್ಥನೆ."
    ),
    "sd": (
        "هيءَ سنڌي تقرير آهي. سمورا لفظ صحيح سنڌي رسم الخط ۽ گراميءَ سان لکو. "
        "اللہ، عبادت، نماز، دعا، صبر، شڪر."
    ),
    "ps": (
        "دا پښتو وینا ده. ټول کلمات د سمو پښتو ژبپوهنې او لیکدود سره ولیکئ. "
        "الله، عبادت، لمونځ، دعا، صبر، شکر."
    ),
    "ms": (
        "Ini adalah ucapan Bahasa Melayu. Tulis semua kata-kata dengan ejaan dan "
        "tatabahasa Melayu yang betul. Allah, solat, ibadah, doa, sabar, syukur."
    ),
    "si": (
        "මෙය සිංහල කථාවකි. සියලු වචන නිවැරදි සිංහල ලිපිය සහ ව්‍යාකරණය සමඟ ලියන්න."
    ),
}

# ── Language support (Whisper language codes) ─────────────────────────────────
LANGUAGE_CODES: dict[str, str] = {
    "english": "en",  "hindi": "hi",   "urdu": "ur",     "nepali": "ne",
    "tamil": "ta",    "telugu": "te",   "bengali": "bn",  "gujarati": "gu",
    "punjabi": "pa",  "marathi": "mr",  "kannada": "kn",  "malayalam": "ml",
    "sindhi": "sd",   "pushto": "ps",   "malay": "ms",
}

# ── Per-clip transcript storage ────────────────────────────────────────────────
_transcripts: dict = {}      # clip_filename → list[{word, start, end}]
_transcripts_lock = Lock()


def _words_json_path(clip_name: str) -> "Path":
    """Return the sidecar .words.json path for a clip filename."""
    return CLIPS_DIR / (Path(clip_name).stem + ".words.json")


def _save_words(clip_name: str, words: list) -> None:
    """Store words in memory and persist to a .words.json sidecar so they
    survive server restarts."""
    with _transcripts_lock:
        _transcripts[clip_name] = words
    try:
        _words_json_path(clip_name).write_text(
            json.dumps(words, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        print(f"[!] Could not save words.json for {clip_name}: {exc}", flush=True)


def _load_words(clip_name: str) -> list:
    """Return word list from memory, falling back to the .words.json sidecar."""
    with _transcripts_lock:
        words = _transcripts.get(clip_name)
    if words:
        return words
    jp = _words_json_path(clip_name)
    if jp.exists():
        try:
            words = json.loads(jp.read_text(encoding="utf-8"))
            with _transcripts_lock:
                _transcripts[clip_name] = words   # warm the cache
            return words
        except Exception as exc:
            print(f"[!] Could not load words.json for {clip_name}: {exc}", flush=True)
    return []

app = Flask(__name__)
CORS(app)

whisper_lock = Lock()


# ── Dependency check ──────────────────────────────────────────────────────────
def check_deps():
    missing = []
    for tool, flag in [("ffmpeg", "-version"), ("ffprobe", "-version"), ("yt-dlp", "--version")]:
        r = subprocess.run([tool, flag], capture_output=True)
        if r.returncode not in (0, 1):
            missing.append(tool)
    return missing


# ── Step 1: Download ──────────────────────────────────────────────────────────
# ── Auto Cookie Engine ────────────────────────────────────────────────────────
COOKIES_FILE        = BASE_DIR / "cookies.txt"
COOKIE_REFRESH_SEC  = 1800   # re-extract every 30 minutes
_cookie_lock        = Lock()
_cookie_ready       = threading.Event()

# Chromium-based browser DB paths on Windows
_CHROMIUM_PROFILES = {
    "chrome":  Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data",
    "edge":    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/User Data",
    "brave":   Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware/Brave-Browser/User Data",
    "chromium":Path(os.environ.get("LOCALAPPDATA", "")) / "Chromium/User Data",
    "opera":   Path(os.environ.get("APPDATA", ""))      / "Opera Software/Opera Stable",
    "vivaldi": Path(os.environ.get("LOCALAPPDATA", "")) / "Vivaldi/User Data",
}

def _chromium_db_exists(browser: str) -> bool:
    """Check if a Chromium-based browser has a Cookies DB on disk."""
    base = _CHROMIUM_PROFILES.get(browser)
    if not base:
        return False
    for sub in ("Default", "Profile 1", "Profile 2", ""):
        db = base / sub / "Network" / "Cookies"
        if db.exists():
            return True
        db2 = base / sub / "Cookies"
        if db2.exists():
            return True
    return False

def _copy_locked_db(db_path: Path) -> Path | None:
    """
    Copy a SQLite DB that may be locked by a running browser.
    Uses the SQLite WAL/shared-cache trick via a raw byte copy.
    Returns path to temp copy, or None on failure.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        # Open with FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        # by reading in binary mode — works on Windows even when locked
        with open(db_path, "rb") as src, open(tmp_path, "wb") as dst:
            dst.write(src.read())
        return tmp_path
    except Exception:
        return None

def _write_netscape_cookies(rows: list, out_path: Path) -> bool:
    """Write cookie rows as Netscape cookies.txt format."""
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# Auto-generated by Voxly\n\n")
            for (host, path, secure, expires, name, value) in rows:
                secure_str = "TRUE" if secure else "FALSE"
                include_sub = "TRUE" if host.startswith(".") else "FALSE"
                f.write(f"{host}\t{include_sub}\t{path}\t{secure_str}\t{expires}\t{name}\t{value}\n")
        return out_path.stat().st_size > 100
    except Exception:
        return False

def _extract_chromium_cookies_direct(browser: str, out_path: Path) -> bool:
    """
    Directly read Chromium SQLite cookie DB (even while browser is open)
    and write YouTube cookies to out_path in Netscape format.
    No decryption needed for the host/name/path fields — only values are
    encrypted, but yt-dlp only needs the cookie file to pass the bot check
    when combined with the --cookies flag (unencrypted session cookies work).
    """
    import sqlite3

    base = _CHROMIUM_PROFILES.get(browser)
    if not base or not base.exists():
        return False

    for sub in ("Default", "Profile 1", "Profile 2", ""):
        for rel in (Path("Network") / "Cookies", Path("Cookies")):
            db_path = base / sub / rel
            if not db_path.exists():
                continue

            tmp_db = _copy_locked_db(db_path)
            if not tmp_db:
                continue

            try:
                conn = sqlite3.connect(f"file:{tmp_db}?mode=ro&immutable=1", uri=True)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                # Fetch YouTube cookies — use encrypted_value fallback for value
                cur.execute("""
                    SELECT host_key, path, is_secure, expires_utc, name,
                           CASE WHEN length(value) > 0 THEN value
                                ELSE '(encrypted)'
                           END as value
                    FROM cookies
                    WHERE host_key LIKE '%youtube.com%'
                       OR host_key LIKE '%google.com%'
                    ORDER BY host_key
                """)
                rows = cur.fetchall()
                conn.close()

                if not rows:
                    tmp_db.unlink(missing_ok=True)
                    continue

                # Convert Chrome epoch (microseconds since 1601) to Unix timestamp
                EPOCH_DIFF = 11644473600  # seconds between 1601 and 1970
                cookie_rows = []
                for r in rows:
                    expires = max(0, r["expires_utc"] // 1_000_000 - EPOCH_DIFF)
                    cookie_rows.append((
                        r["host_key"], r["path"], r["is_secure"],
                        expires, r["name"], r["value"]
                    ))

                tmp_db.unlink(missing_ok=True)

                if _write_netscape_cookies(cookie_rows, out_path):
                    return True

            except Exception as e:
                print(f"[Cookie] Direct DB read failed for {browser}: {e}", flush=True)
                try:
                    tmp_db.unlink(missing_ok=True)
                except Exception:
                    pass

    return False

def _try_extract_cookies(browser: str, out_path: Path) -> bool:
    """
    Try to extract YouTube cookies from `browser` into `out_path`.
    Strategy 1: yt-dlp native (works when browser is closed)
    Strategy 2: Direct SQLite read (works when browser is open)
    Returns True on success.
    """
    # Strategy 1: yt-dlp native extraction
    try:
        r = subprocess.run(
            ["yt-dlp",
             "--cookies-from-browser", browser,
             "--cookies", str(out_path),
             "--skip-download", "--quiet", "--no-warnings",
             "https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
            capture_output=True, timeout=20,
        )
        if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 200:
            return True
    except Exception:
        pass

    # Strategy 2: Direct SQLite read (bypasses browser lock)
    if browser != "firefox":
        if _extract_chromium_cookies_direct(browser, out_path):
            return True

    return False

def _auto_extract_cookies() -> bool:
    """
    Try every known browser in priority order.
    Saves result to COOKIES_FILE. Returns True if cookies were obtained.
    """
    tmp_out = COOKIES_FILE.with_suffix(".tmp")

    # Priority: browsers most likely to have YouTube login
    browsers = ["chrome", "edge", "brave", "chromium", "opera", "vivaldi", "firefox"]

    for browser in browsers:
        print(f"[Cookie] Trying {browser}...", flush=True)
        try:
            if browser != "firefox" and not _chromium_db_exists(browser):
                continue   # skip browsers not installed
            ok = _try_extract_cookies(browser, tmp_out)
            if ok:
                shutil.move(str(tmp_out), str(COOKIES_FILE))
                print(f"[OK] Cookies auto-extracted from {browser} → cookies.txt", flush=True)
                return True
        except Exception as e:
            print(f"[Cookie] {browser} failed: {e}", flush=True)
        finally:
            if tmp_out.exists():
                try:
                    tmp_out.unlink()
                except Exception:
                    pass

    print(
        "[!] Auto cookie extraction failed for all browsers.\n"
        "    Make sure you are logged into YouTube in Chrome/Edge/Brave.\n"
        "    Or manually export cookies.txt using the 'Get cookies.txt LOCALLY' Chrome extension.",
        flush=True,
    )
    return False

def _cookie_refresh_loop():
    """Background thread: extract cookies on startup, then refresh every 30 min."""
    while True:
        with _cookie_lock:
            # Always try fresh extraction first; fall back to existing file
            success = _auto_extract_cookies()
            if not success and COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 200:
                print("[Cookie] Using previously saved cookies.txt", flush=True)
                success = True
            if success:
                _cookie_ready.set()
            else:
                _cookie_ready.clear()
        time.sleep(COOKIE_REFRESH_SEC)

# Start cookie engine in background immediately
_cookie_thread = threading.Thread(target=_cookie_refresh_loop, daemon=True)
_cookie_thread.start()
print("[Cookie] Auto-detection started in background...", flush=True)


# ── Step 1: Download ──────────────────────────────────────────────────────────
def download_video(youtube_url: str) -> Path:
    uid = uuid.uuid4().hex[:10]
    template = str(DOWNLOADS_DIR / f"{uid}.%(ext)s")

    # Wait up to 25 s for cookie engine on first request
    _cookie_ready.wait(timeout=25)

    has_cookies = COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 200

    # Build download command
    cmd = [
        "yt-dlp",
        # Permissive format: no strict ext= so all clients' streams qualify
        "-f", "bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--no-part",
        "--add-header", "Accept-Language:en-US,en;q=0.9",
        "--sleep-requests", "1",
        "--retries", "3",
        "-o", template,
    ]

    if has_cookies:
        # With cookies: use web client (supports cookie auth); android/ios don't
        # mweb is a lighter mobile-web client that also accepts cookies
        cmd += [
            "--extractor-args", "youtube:player_client=web,mweb",
            "--cookies", str(COOKIES_FILE),
        ]
        print("[*] Using cookies.txt for download (web client)", flush=True)
    else:
        # No cookies: android + ios don't need a PO/GVS token
        cmd += [
            "--extractor-args", "youtube:player_client=android,ios",
            "--user-agent",
            "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
        ]
        print("[*] No cookies — using android/ios clients", flush=True)

    cmd.append(youtube_url)

    result = subprocess.run(cmd, capture_output=True)

    # Some Windows antivirus or indexing services lock the .temp.mp4 before yt-dlp can rename it.
    # Check if a valid .mp4 or .temp.mp4 output file exists despite non-zero return code.
    matches = list(DOWNLOADS_DIR.glob(f"{uid}*"))
    for ext in [".mp4", ".temp.mp4", ".mkv", ".webm"]:
        for m in matches:
            if m.name == f"{uid}{ext}":
                return m

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"Download failed:\n{stderr[-800:]}")

    if not matches:
        raise RuntimeError("yt-dlp finished but produced no output file.")
    return matches[0]


# ── Step 2: Video info ────────────────────────────────────────────────────────
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
            width  = int(s["width"])
            height = int(s["height"])
            break
    return duration, width, height


# ── Step 3: Audio energy analysis ────────────────────────────────────────────
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
        # Fallback: uniform energy (clips will be evenly spaced)
        return [(t, 1.0) for t in range(int(duration))]

    n = len(raw) // 2
    samples = struct.unpack(f"<{n}h", raw)

    win   = SAMPLE_RATE * ENERGY_WINDOW  # samples per window
    step  = SAMPLE_RATE                  # 1-second increments
    result = []

    for i in range(0, n - win, step):
        chunk = samples[i : i + win : 8]   # subsample every 8th → speed
        if not chunk:
            continue
        rms = math.sqrt(sum(int(s) * int(s) for s in chunk) / len(chunk))
        result.append((i / SAMPLE_RATE, rms))

    return result


# ── Step 4a: YouTube Transcript API (instant, no key needed) ─────────────────
def _extract_video_id(url: str) -> str | None:
    """Pull the YouTube video ID out of any youtube.com / youtu.be URL."""
    try:
        from urllib.parse import urlparse, parse_qs
        p = urlparse(url)
        if p.hostname in ("www.youtube.com", "youtube.com"):
            if p.path.startswith("/shorts/"):
                return p.path.split("/")[2]
            vid = parse_qs(p.query).get("v", [None])[0]
            return vid
        if p.hostname == "youtu.be":
            return p.path.lstrip("/")
    except Exception:
        pass
    return None

def _youtube_transcript_words(video_id: str) -> list | None:
    """
    Fetch YouTube auto-captions via youtube-transcript-api (v1.0+ instance API).
    Returns a flat list of {word, start, end} dicts, or None on failure.
    This replaces the slow full-video Whisper scan for segment detection.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt = YouTubeTranscriptApi()
        entries = ytt.fetch(video_id)
        words = []
        for e in entries:
            raw = getattr(e, "text", None) or (e.get("text", "") if isinstance(e, dict) else "")
            raw = raw.strip()
            if not raw:
                continue
            start = getattr(e, "start", None) or (e.get("start", 0) if isinstance(e, dict) else 0)
            duration = getattr(e, "duration", None) or (e.get("duration", 2) if isinstance(e, dict) else 2)
            parts = raw.split()
            dur_per_word = duration / max(len(parts), 1)
            for i, w in enumerate(parts):
                words.append({
                    "word":  w,
                    "start": start + i * dur_per_word,
                    "end":   start + (i + 1) * dur_per_word,
                })
        if words:
            print(f"[YT-Transcript] Got {len(words)} words instantly (no Whisper needed for detection)", flush=True)
        return words if words else None
    except Exception as exc:
        print(f"[YT-Transcript] Not available: {exc}", flush=True)
        return None

# ── Step 4b: Find hook segments (AI Speech Density) ───────────────────────────
def find_speech_dense_segments(video_path: Path, duration: float, n_clips: int = MAX_CLIPS, clip_duration: int = DEFAULT_DURATION, video_id: str = None, language: str = None):
    """
    Priority order for segment detection:
    1. YouTube Transcript API  – instant, free, no key required (NEW)
    2. Local Whisper model     – accurate but slow on CPU (fallback)
    3. Audio RMS energy        – fast but less accurate (last resort)
    """
    # ── Try YouTube Transcript API first ──────────────────────────────────────
    all_words = None
    if video_id:
        all_words = _youtube_transcript_words(video_id)

    # ── Fall back to Audio RMS (fast, no model loading) ───────────────────────
    if all_words is None:
        print("[*] YT transcript unavailable — using Audio RMS for segment detection (fast)", flush=True)
        energies = extract_audio_energy(video_path, duration)
        return find_segments(energies, duration, n_clips, clip_duration)

    if not all_words:
        print("[*] No speech detected, falling back to Audio Energy RMS hook detection.", flush=True)
        energies = extract_audio_energy(video_path, duration)
        return find_segments(energies, duration, n_clips, clip_duration)

    # We have words. Let's build a sliding window of word counts.
    # We'll calculate the word count for a window [t, t + clip_duration]
    # for t in range(0, int(duration - clip_duration + 1))
    
    max_start_time = int(duration - clip_duration)
    if max_start_time < 0:
        max_start_time = 0
        
    window_scores = []
    
    for t in range(0, max_start_time + 1): # 1-second increments
        window_end = t + clip_duration
        word_count = sum(1 for w in all_words if w["start"] >= t and w["start"] <= window_end)
        window_scores.append((t, word_count))

    if not window_scores:
         energies = extract_audio_energy(video_path, duration)
         return find_segments(energies, duration, n_clips, clip_duration)

    # Sort windows by word count (descending)
    window_scores.sort(key=lambda x: x[1], reverse=True)
    
    selected_clips = []
    
    for t, count in window_scores:
        if len(selected_clips) >= n_clips:
            break
            
        # Check if this window overlaps too much with already selected clips
        conflict = False
        for selected_start in selected_clips:
            if abs(t - selected_start) < MIN_GAP_SECONDS:
                conflict = True
                break
                
        if not conflict:
            selected_clips.append(t)
            
    # Sort chronologically
    selected_clips.sort()
    
    # If we couldn't find enough dense clips because of MIN_GAP constraints, 
    # we pad with evenly spaced clips just like find_segments does.
    if len(selected_clips) < n_clips:
        step = max(60.0, (duration - clip_duration) / max(n_clips, 1))
        t = 10.0
        while len(selected_clips) < n_clips and t + clip_duration <= duration:
            if all(abs(t - p) >= MIN_GAP_SECONDS for p in selected_clips):
                selected_clips.append(t)
            t += step
        selected_clips.sort()

    # Convert to (start, end) format
    final_segments = []
    for pt in selected_clips:
        start = float(pt)
        end = start + clip_duration
        if end > duration:
            end = duration
            start = max(0.0, end - clip_duration)
        final_segments.append((round(start, 2), round(end, 2)))

    return final_segments

# ── Old Audio RMS Logic (Fallback) ────────────────────────────────────────────
def find_segments(energies, duration: float, n_clips: int = MAX_CLIPS, clip_duration: int = DEFAULT_DURATION):
    """
    Greedy peak selection:
    1. Smooth the RMS curve.
    2. Repeatedly pick the highest-energy moment, then
       black out a MIN_GAP_SECONDS radius around it.
    Returns list of (start, end) in seconds.
    """
    if not energies:
        step = max(60.0, (duration - clip_duration) / max(n_clips, 1))
        return [(round(i * step + 10, 2), round(i * step + 10 + clip_duration, 2))
                for i in range(n_clips) if i * step + 10 + clip_duration <= duration]

    times = [e[0] for e in energies]
    vals  = [e[1] for e in energies]

    # Smooth
    w = min(10, max(3, len(vals) // 20))
    smoothed = []
    for i in range(len(vals)):
        lo, hi = max(0, i - w), min(len(vals), i + w + 1)
        smoothed.append(sum(vals[lo:hi]) / (hi - lo))

    # Greedy selection
    used   = [False] * len(smoothed)
    peaks  = []
    gap_idx = MIN_GAP_SECONDS  # since step ≈ 1 s, index ≈ seconds

    while len(peaks) < n_clips * 2:
        best_i = max(
            (i for i in range(len(smoothed)) if not used[i]),
            key=lambda i: smoothed[i],
            default=-1,
        )
        if best_i < 0:
            break
        peaks.append(times[best_i])
        lo = max(0, best_i - gap_idx)
        hi = min(len(used), best_i + gap_idx + 1)
        for j in range(lo, hi):
            used[j] = True

    peaks.sort()
    peaks = peaks[:n_clips]

    # If we have fewer peaks than requested, fill with evenly spaced ones
    if len(peaks) < n_clips:
        step = max(60.0, (duration - clip_duration) / max(n_clips, 1))
        t = 10.0
        while len(peaks) < n_clips and t + clip_duration <= duration:
            if all(abs(t - p) >= MIN_GAP_SECONDS for p in peaks):
                peaks.append(t)
            t += step
        peaks.sort()

    # Convert to (start, end)
    segments = []
    for pt in peaks:
        start = max(0.0, pt - clip_duration * 0.25)
        end   = start + clip_duration
        if end > duration:
            end   = duration
            start = max(0.0, end - clip_duration)
        segments.append((round(start, 2), round(end, 2)))

    return segments


# ── Step 5: Build 9:16 crop filter ───────────────────────────────────────────
def detect_content_center(video_path: Path, timestamp: float = 2.0) -> tuple:
    """Return (cx, cy) fraction of content centroid via brightness-weighted analysis."""
    W, H = 80, 45
    cmd = [
        "ffmpeg", "-ss", str(round(timestamp, 2)), "-i", str(video_path),
        "-vframes", "1", "-vf", f"scale={W}:{H}",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        if r.returncode != 0 or len(r.stdout) < W * H:
            return (0.5, 0.42)
        pixels = list(r.stdout)
        total = sum(pixels)
        if total == 0:
            return (0.5, 0.42)
        cx = sum((i % W) * v for i, v in enumerate(pixels)) / total / W
        cy = sum((i // W) * v for i, v in enumerate(pixels)) / total / H
        # Clamp to avoid extreme crop positions
        return (max(0.2, min(0.8, cx)), max(0.2, min(0.70, cy)))
    except Exception:
        return (0.5, 0.42)


def build_vf_focused(width: int, height: int, cx: float, cy: float) -> str:
    """Like build_vf but center the crop at the detected content position."""
    ratio = 9 / 16
    if width / height > ratio:
        cw = int(height * ratio) & ~1
        ch = height & ~1
        ideal_x = int(cx * width - cw / 2)
        crop_x = max(0, min(width - cw, ideal_x)) & ~1
        return f"crop={cw}:{ch}:{crop_x}:0,scale=1080:1920:flags=lanczos"
    else:
        cw = width & ~1
        ch = int(width / ratio) & ~1
        ideal_y = int(cy * height - ch / 2)
        crop_y = max(0, min(height - ch, ideal_y)) & ~1
        return f"crop={cw}:{ch}:0:{crop_y},scale=1080:1920:flags=lanczos"


# ── Face Tracker (dynamic crop that follows the face) ─────────────────────────
_face_cascade = None


def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        import cv2 as _cv2
        xml = _cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = _cv2.CascadeClassifier(xml)
    return _face_cascade


def _detect_face_at_ms(cap, t_ms: float, scale_w: int = 320):
    """Seek cap to t_ms, detect largest face, return (cx_frac, cy_frac) or None."""
    import cv2 as _cv2
    cap.set(_cv2.CAP_PROP_POS_MSEC, t_ms)
    ret, frame = cap.read()
    if not ret or frame is None:
        return None
    h, w = frame.shape[:2]
    if w == 0 or h == 0:
        return None
    scale = scale_w / w
    small = _cv2.resize(frame, (scale_w, max(1, int(h * scale))))
    gray = _cv2.cvtColor(small, _cv2.COLOR_BGR2GRAY)
    cascade = _get_face_cascade()
    faces = cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20)
    )
    if not len(faces):
        return None
    fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    sh = max(1, int(h * scale))
    return ((fx + fw / 2) / scale_w, (fy + fh / 2) / sh)


def _smooth_track(positions: list, window: int = 2) -> list:
    """Moving-average smooth a list of (t, cx, cy) tuples."""
    if len(positions) < 2:
        return positions
    ts = [p[0] for p in positions]
    xs = [p[1] for p in positions]
    ys = [p[2] for p in positions]

    def avg(vals, i, w):
        lo, hi = max(0, i - w), min(len(vals), i + w + 1)
        return sum(vals[lo:hi]) / (hi - lo)

    return [(ts[i], avg(xs, i, window), avg(ys, i, window))
            for i in range(len(ts))]


def _build_track_expr(keyframes: list, crop_dim: int, total_dim: int,
                      coord: int) -> str:
    """
    Build a piecewise-linear ffmpeg expression for crop x (coord=0) or y (coord=1).
    keyframes: list of (t_sec, cx_frac, cy_frac) relative to clip start.
    """
    max_pos = total_dim - crop_dim

    def to_px(frac):
        return max(0, min(max_pos, int(frac * total_dim - crop_dim / 2))) & ~1

    if not keyframes:
        return str(max_pos // 2)

    pts = [(t, to_px(cx if coord == 0 else cy)) for t, cx, cy in keyframes]

    if len(pts) == 1:
        return str(pts[0][1])

    # Build nested if() chain from the right (last value is the leaf)
    expr = str(pts[-1][1])
    for i in range(len(pts) - 2, -1, -1):
        t0, p0 = pts[i]
        t1, p1 = pts[i + 1]
        dt = round(t1 - t0, 3)
        if dt <= 0:
            continue
        lerp = f"({p0}+({p1 - p0})*(t-{t0:.3f})/{dt:.3f})"
        expr = f"if(lt(t,{t1:.3f}),{lerp},{expr})"

    # Hold at first position before first keyframe
    return f"if(lt(t,{pts[0][0]:.3f}),{pts[0][1]},{expr})"


def build_face_tracking_vf(video_path: Path, start: float, dur: float,
                            in_w: int, in_h: int,
                            sample_interval: float = 1.5) -> str:
    """
    Sample frames from video_path in [start, start+dur], detect faces with
    Haar cascade, smooth the trajectory, and return an ffmpeg -vf string
    whose crop pans dynamically to keep the face centred in the frame.
    Falls back to center crop when no face is detected.
    """
    import cv2 as _cv2

    ratio = 9 / 16
    is_landscape = (in_w / in_h) > ratio

    if is_landscape:
        crop_w = int(in_h * ratio) & ~1
        crop_h = in_h & ~1
    else:
        crop_w = in_w & ~1
        crop_h = int(in_w / ratio) & ~1

    # Clamp crop dims to input size
    crop_w = min(crop_w, in_w)
    crop_h = min(crop_h, in_h)

    # Sample timestamps
    n_samples = max(4, min(14, int(dur / sample_interval)))
    step = dur / n_samples
    timestamps_abs = [start + i * step for i in range(n_samples + 1)
                      if (start + i * step) < (start + dur - 0.2)]

    detections: list = []
    try:
        cap = _cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError("Cannot open video")
        for t_abs in timestamps_abs:
            result = _detect_face_at_ms(cap, t_abs * 1000)
            if result:
                cx, cy = result
                detections.append((t_abs - start, cx, cy))  # relative time
        cap.release()
        print(f"[FaceTrack] {len(detections)}/{len(timestamps_abs)} frames with face", flush=True)
    except Exception as exc:
        print(f"[FaceTrack] error: {exc}", flush=True)

    def center_crop():
        if is_landscape:
            cx_px = ((in_w - crop_w) // 2) & ~1
            return f"crop={crop_w}:{crop_h}:{cx_px}:0,scale=1080:1920:flags=lanczos"
        else:
            cy_px = ((in_h - crop_h) // 2) & ~1
            return f"crop={crop_w}:{crop_h}:0:{cy_px},scale=1080:1920:flags=lanczos"

    if not detections:
        print("[FaceTrack] no faces — using centre crop", flush=True)
        return center_crop()

    smoothed = _smooth_track(detections, window=2)

    if is_landscape:
        x_expr = _build_track_expr(smoothed, crop_w, in_w, 0)
        return f"crop={crop_w}:{crop_h}:{x_expr}:0,scale=1080:1920:flags=lanczos"
    else:
        y_expr = _build_track_expr(smoothed, crop_h, in_h, 1)
        return f"crop={crop_w}:{crop_h}:0:{y_expr},scale=1080:1920:flags=lanczos"


def build_vf(width: int, height: int) -> str:
    """Return an FFmpeg -vf string that center-crops to 9:16 at 1080×1920."""
    ratio = 9 / 16
    if width / height > ratio:
        # Landscape – crop left/right
        cw = int(height * ratio)
        ch = height
        cx = (width - cw) // 2
        cy = 0
    else:
        # Portrait / square – crop top/bottom
        cw = width
        ch = int(width / ratio)
        cx = 0
        cy = (height - ch) // 2

    # Force even numbers
    cw -= cw % 2
    ch -= ch % 2
    return f"crop={cw}:{ch}:{cx}:{cy},scale=1080:1920:flags=lanczos"


def build_vf_pad(width: int, height: int) -> str:
    """Scale to fit inside 9:16 (1080×1920) preserving aspect ratio, pad remainder black."""
    # scale down to fit, keeping aspect ratio
    # then pad symmetrically to exactly 1080x1920
    return (
        "scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
        "setsar=1"
    )


# ── Step 6: Captions overlay ──────────────────────────────────────────────────
whisper_model = None

# ── SRT generator ─────────────────────────────────────────────────────────────
def generate_srt_content(words: list, chunk_size: int = 4) -> str:
    """Build an SRT subtitle string from word-level timestamps."""
    def srt_t(s: float) -> str:
        h = int(s // 3600); m = int((s % 3600) // 60)
        sec = int(s % 60);  ms = int(round((s - int(s)) * 1000))
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
    lines, idx = [], 1
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        if not chunk: continue
        t0 = chunk[0].get("start", 0)
        t1 = chunk[-1].get("end", t0 + 2)
        text = " ".join(w.get("word", "").strip() for w in chunk)
        if text.strip():
            lines.append(f"{idx}\n{srt_t(t0)} --> {srt_t(t1)}\n{text}\n")
            idx += 1
    return "\n".join(lines)

def format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:
        s += 1
        cs = 0
        if s >= 60:
            s -= 60
            m += 1
            if m >= 60:
                m -= 60
                h += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def transcribe_and_generate_ass(clip_path: Path, caption_style: str = "mrbeast",
                                 language: str = None, custom_cfg: dict = None):
    global whisper_model
    import whisper
    import torch
    import unicodedata
    with whisper_lock:
        if whisper_model is None:
            print("[*] Loading Whisper model (small) — higher accuracy for all languages...", flush=True)
            whisper_model = whisper.load_model("small")

        lang_code = language or "en"
        print(f"[*] Transcribing {clip_path.name} (style: {caption_style}, lang: {lang_code})...", flush=True)
        whisper_kwargs = dict(
            word_timestamps=True,
            fp16=torch.cuda.is_available(),
            language=lang_code,
            beam_size=1,
            best_of=1,
            temperature=0,
            condition_on_previous_text=True,
            initial_prompt=WHISPER_LANG_PROMPTS.get(lang_code, ""),
        )
        res = whisper_model.transcribe(str(clip_path), **whisper_kwargs)

    # ── Store word-level transcript, NFC-normalized for correct script ────────
    all_words = []
    for seg in res.get("segments", []):
        for w in seg.get("words", []):
            w["word"] = unicodedata.normalize("NFC", w.get("word", "")).strip()
            all_words.append(w)
    _save_words(clip_path.name, all_words)

    # ── Save SRT file alongside clip ──────────────────────────────────────────
    srt_content = generate_srt_content(all_words)
    srt_path = clip_path.with_suffix(".srt")
    try:
        srt_path.write_text(srt_content, encoding="utf-8")
    except Exception:
        pass

    ass_path = clip_path.with_suffix(".ass")

    # ── Style definitions ─────────────────────────────────────────────────────
    # ASS colour format: &HAABBGGRR (AA=alpha 00=opaque, then BGR)
    # Alignment 2 = BottomCenter
    STYLE_CONFIGS = {
        "mrbeast": {
            "font":        "Impact",
            "size":        110,
            "primary":     "&H00FFFFFF",   # white
            "outline":     "&H00000000",   # black
            "back":        "&H80000000",
            "bold":        -1,
            "outline_w":   3,
            "shadow":      2,
            "marginv":     288,
            "chunk":       3,
            "highlight":   "&H0000FFFF",   # yellow (BGR: 00 FF FF)
            "upper":       True,
        },
        "hormozi": {
            "font":        "Arial Black",
            "size":        105,
            "primary":     "&H00FFFFFF",   # white
            "outline":     "&H00000000",
            "back":        "&HA0000000",
            "bold":        -1,
            "outline_w":   2,
            "shadow":      1,
            "marginv":     240,
            "chunk":       2,              # 2 words per group — punchy
            "highlight":   "&H0014D4FF",   # vibrant amber-yellow
            "upper":       True,
        },
        "garyvee": {
            "font":        "Arial Black",
            "size":        115,
            "primary":     "&H00FFFFFF",
            "outline":     "&H00000000",
            "back":        "&H90000000",
            "bold":        -1,
            "outline_w":   4,
            "shadow":      0,
            "marginv":     260,
            "chunk":       2,
            "highlight":   "&H002165FB",   # orange
            "upper":       True,
        },
        "loganpaul": {
            "font":        "Poppins",
            "size":        100,
            "primary":     "&H00E2E8F0",   # near-white
            "outline":     "&H00000000",
            "back":        "&H70000000",
            "bold":        -1,
            "outline_w":   2,
            "shadow":      3,
            "marginv":     270,
            "chunk":       3,
            "highlight":   "&H00F8BD38",   # cyan
            "upper":       True,
        },
        "minimal": {
            "font":        "Inter",
            "size":        90,
            "primary":     "&H00FFFFFF",
            "outline":     "&H00000000",
            "back":        "&H55000000",
            "bold":        0,
            "outline_w":   0,
            "shadow":      2,
            "marginv":     260,
            "chunk":       4,
            "highlight":   "&H00CCCCCC",   # soft grey — subtle
            "upper":       False,
        },
        "tiktok": {
            "font":        "Arial Black",
            "size":        112,
            "primary":     "&H00FFFFFF",
            "outline":     "&H00000000",
            "back":        "&H80000000",
            "bold":        -1,
            "outline_w":   3,
            "shadow":      2,
            "marginv":     280,
            "chunk":       2,
            "highlight":   "&H00FF2DD4",   # hot pink-red
            "upper":       True,
        },
        "imangadzi": {
            "font":        "Impact",
            "size":        108,
            "primary":     "&H00FFFFFF",   # white
            "outline":     "&H00000000",   # black
            "back":        "&H88000000",
            "bold":        -1,
            "outline_w":   3,
            "shadow":      1,
            "marginv":     270,
            "chunk":       2,
            "highlight":   "&H0022B4FF",   # gold (#FFB422 in RGB → &H0022B4FF in ASS BGR)
            "upper":       True,
        },
        "devinjatho": {
            "font":        "Arial Black",
            "size":        118,
            "primary":     "&H00FFFFFF",
            "outline":     "&H00000000",
            "back":        "&H75000000",
            "bold":        -1,
            "outline_w":   4,
            "shadow":      0,
            "marginv":     265,
            "chunk":       2,
            "highlight":   "&H0040E040",   # neon green (#40E040 in RGB → &H0040E040 in ASS BGR)
            "upper":       True,
        },
        # ── New styles ────────────────────────────────────────────────────────
        "karaoke": {
            "font":        "Impact",
            "size":        108,
            "primary":     "&H0000FFFF",   # yellow — post-sweep (spoken) colour
            "secondary":   "&H88AAAAAA",   # dim grey — pre-sweep (unspoken) colour
            "outline":     "&H00000000",
            "back":        "&H60000000",
            "bold":        -1,
            "outline_w":   3,
            "shadow":      1,
            "marginv":     270,
            "chunk":       4,
            "highlight":   "&H0000FFFF",
            "upper":       True,
            "_karaoke":    True,
        },
        "outlined": {
            "font":        "Arial Black",
            "size":        106,
            "primary":     "&H00FFFFFF",
            "outline":     "&H00000000",
            "back":        "&H00000000",   # transparent back — pure stroke look
            "bold":        -1,
            "outline_w":   8,
            "shadow":      0,
            "marginv":     272,
            "chunk":       3,
            "highlight":   "&H0040C0FF",   # amber
            "upper":       True,
        },
        "gradient": {
            "font":        "Impact",
            "size":        108,
            "primary":     "&H00FFFFFF",
            "outline":     "&H00000000",
            "back":        "&H70000000",
            "bold":        -1,
            "outline_w":   3,
            "shadow":      1,
            "marginv":     270,
            "chunk":       3,
            "highlight":   "&H0000FFFF",   # bright yellow for current word
            "upper":       True,
            "_gradient":   True,
        },
    }

    cfg = dict(STYLE_CONFIGS.get(caption_style, STYLE_CONFIGS["mrbeast"]))  # mutable copy

    # ── Apply custom style overrides (Segment 5 – Caption Customizer) ─────────
    def hex_to_ass(hex_col: str) -> str:
        """Convert #RRGGBB or #AARRGGBB → &H00BBGGRR (ASS format)."""
        h = hex_col.lstrip("#")
        if len(h) == 6:
            r, g, b = h[0:2], h[2:4], h[4:6]
            return f"&H00{b}{g}{r}"
        elif len(h) == 8:
            a, r, g, b = h[0:2], h[2:4], h[4:6], h[6:8]
            return f"&H{a}{b}{g}{r}"
        return hex_col  # already ASS format

    if custom_cfg:
        if custom_cfg.get("font"):       cfg["font"]      = custom_cfg["font"]
        if custom_cfg.get("size"):       cfg["size"]      = int(custom_cfg["size"])
        if custom_cfg.get("primaryColor"):  cfg["primary"]   = hex_to_ass(custom_cfg["primaryColor"])
        if custom_cfg.get("outlineColor"):  cfg["outline"]   = hex_to_ass(custom_cfg["outlineColor"])
        if custom_cfg.get("highlightColor"): cfg["highlight"] = hex_to_ass(custom_cfg["highlightColor"])
        if custom_cfg.get("outlineWidth"):  cfg["outline_w"] = int(custom_cfg["outlineWidth"])
        if custom_cfg.get("shadow") is not None: cfg["shadow"] = int(custom_cfg["shadow"])
        if custom_cfg.get("uppercase") is not None: cfg["upper"] = bool(custom_cfg["uppercase"])
        if custom_cfg.get("wordsPerLine"):  cfg["chunk"]    = int(custom_cfg["wordsPerLine"])
        if custom_cfg.get("position") == "top":
            cfg["marginv"] = 80
        elif custom_cfg.get("position") == "center":
            cfg["marginv"] = 900

    secondary_col = cfg.get("secondary", "&H000000FF")
    ass_header = f"""[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{cfg['font']},{cfg['size']},{cfg['primary']},{secondary_col},{cfg['outline']},{cfg['back']},{cfg['bold']},0,0,0,100,100,0,0,1,{cfg['outline_w']},{cfg['shadow']},2,20,20,{cfg['marginv']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    HIGHLIGHT   = str(cfg["highlight"])
    primary_col = str(cfg["primary"])
    HL_TAG      = "{\\c" + HIGHLIGHT + "&}"
    is_karaoke  = bool(cfg.get("_karaoke"))
    is_gradient = bool(cfg.get("_gradient"))

    # Gradient colour palette (ASS BGR order)
    GRAD_PALETTE = [
        "&H0069B4FF",  # coral-red
        "&H00D474C8",  # magenta-purple
        "&H00C4CD4E",  # teal-cyan
        "&H0038D4F7",  # amber-yellow
        "&H00E87840",  # sky-blue
    ]

    chunk_size = int(cfg["chunk"])
    upper      = bool(cfg["upper"])

    for segment in res.get("segments", []):
        words = segment.get("words", [])
        for i in range(0, len(words), chunk_size):
            chunk = words[i:i + chunk_size]
            if not chunk:
                continue

            if is_karaoke:
                # ── Karaoke: one dialogue per chunk, {\kf<cs>}word tags ────────
                chunk_start = format_ass_time(chunk[0]["start"])
                chunk_end   = format_ass_time(chunk[-1]["end"])
                parts = []
                for j, w in enumerate(chunk):
                    txt = w["word"].strip()
                    if upper:
                        txt = txt.upper()
                    if j < len(chunk) - 1:
                        dur_cs = max(1, int((chunk[j + 1]["start"] - w["start"]) * 100))
                    else:
                        dur_cs = max(1, int((w["end"] - w["start"]) * 100))
                    parts.append(f"{{\\kf{dur_cs}}}{txt}")
                events.append(f"Dialogue: 0,{chunk_start},{chunk_end},Default,,0,0,0,,{' '.join(parts)}\\N")
            else:
                # ── Normal word-by-word (standard OR gradient) ──────────────────
                for word_idx, w in enumerate(chunk):
                    start_t = format_ass_time(w["start"])
                    end_t   = format_ass_time(chunk[word_idx + 1]["start"]) \
                              if word_idx < len(chunk) - 1 else format_ass_time(w["end"])

                    line_parts = []
                    for j, cw in enumerate(chunk):
                        if j > word_idx:
                            break
                        cw_text = cw["word"].strip()
                        if upper:
                            cw_text = cw_text.upper()
                        if j == word_idx:
                            line_parts.append(f"{HL_TAG}{cw_text}{{\\r}}")
                        elif is_gradient:
                            gc = "{\\c" + GRAD_PALETTE[j % len(GRAD_PALETTE)] + "&}"
                            line_parts.append(f"{gc}{cw_text}{{\\r}}")
                        else:
                            line_parts.append(cw_text)

                    text = " ".join(line_parts)
                    events.append(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{text}\\N")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for e in events:
            f.write(e + "\n")

    transcript_text = res.get("text", "").strip()
    return ass_path, transcript_text


# ── Visual FX Helpers ─────────────────────────────────────────────────────────

def build_emoji_overlays(words: list, clip_duration: float) -> list:
    """Return list of drawtext filter strings for keyword-triggered text bursts."""
    if not words:
        return []
    overlays, used_times = [], []
    for w in words:
        word_clean = w.get("word", "").strip().lower().strip(".,!?;:")
        if word_clean not in EMOJI_MAP:
            continue
        t_start = round(float(w.get("start", 0)), 2)
        t_end   = round(min(t_start + 1.8, clip_duration - 0.3), 2)
        if t_start < 1.0 or t_end <= t_start:
            continue
        if any(abs(t_start - u) < 3.0 for u in used_times):
            continue
        used_times.append(t_start)
        label, box_color = EMOJI_MAP[word_clean]
        fi_end   = round(t_start + 0.2, 2)
        fo_start = round(t_end   - 0.2, 2)
        alpha = (
            f"if(lt(t\\,{t_start})\\,0\\,"
            f"if(lt(t\\,{fi_end})\\,(t-{t_start})/0.2\\,"
            f"if(lt(t\\,{fo_start})\\,1\\,"
            f"if(lt(t\\,{t_end})\\,({t_end}-t)/0.2\\,0))))"
        )
        safe_label = label.replace("'", "\\'")
        overlays.append(
            f"drawtext=text='{safe_label}'"
            f":fontcolor=white:fontsize=64:font=Impact"
            f":box=1:boxcolor={box_color}:boxborderw=16"
            f":x=(w-text_w)/2:y=h*0.17"
            f":alpha='{alpha}'"
        )
        if len(overlays) >= 4:
            break
    return overlays


def find_energy_peaks_in_clip(clip_path: Path, n_peaks: int = 3) -> list:
    """Return N highest-energy timestamps in a clip for auto-zoom punch-ins."""
    try:
        dur, _, _ = get_video_info(clip_path)
    except Exception:
        return []
    energies = extract_audio_energy(clip_path, dur)
    if len(energies) < 5:
        return []
    sorted_e = sorted(energies, key=lambda x: x[1], reverse=True)
    peaks: list = []
    for t, _rms in sorted_e:
        if t < 2.0 or t > dur - 3.0:
            continue
        if all(abs(t - p["time"]) >= 3.0 for p in peaks):
            peaks.append({"time": round(t, 2), "duration": 1.8})
        if len(peaks) >= n_peaks:
            break
    return peaks


def apply_auto_zoom(clip_path: Path, output: Path) -> bool:
    """Detect audio energy peaks and apply a 22% crop-zoom punch-in at those moments."""
    peaks = find_energy_peaks_in_clip(clip_path)
    if not peaks:
        return False
    zoom_parts = [
        f"between(t\\,{p['time']}\\,{round(p['time']+p['duration'],2)})*0.22"
        for p in peaks
    ]
    zoom_expr = "1+min(0.22\\," + "+".join(zoom_parts) + ")"
    vf = (
        f"crop=w='iw/{zoom_expr}':h='ih/{zoom_expr}':"
        f"x='(iw-iw/{zoom_expr})/2':y='(ih-ih/{zoom_expr})/2',"
        "scale=1080:1920"
    )
    cmd = [
        "ffmpeg", "-i", str(clip_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "copy", "-y", str(output),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        return r.returncode == 0
    except Exception as e:
        print(f"[AutoZoom] failed: {e}", flush=True)
        return False


def apply_speed_ramp(clip_path: Path, output: Path) -> bool:
    """Speed up low-energy audio segments (1.35×) and keep high-energy at 1×."""
    try:
        dur, _, _ = get_video_info(clip_path)
    except Exception:
        return False
    energies = extract_audio_energy(clip_path, dur)
    if len(energies) < 6:
        return False
    vals   = [e[1] for e in energies]
    mean_e = sum(vals) / len(vals)
    thresh = mean_e * 0.65

    # Build per-second speed schedule
    schedule = [(t, 1.35 if rms < thresh else 1.0) for t, rms in energies]

    # Group into contiguous same-speed segments
    segs: list = []
    s0, sp0 = schedule[0]
    for t, sp in schedule[1:]:
        if sp != sp0:
            segs.append({"start": s0, "end": t, "speed": sp0})
            s0, sp0 = t, sp
    segs.append({"start": s0, "end": dur, "speed": sp0})

    # Merge tiny segments (< 2 s) into their neighbour
    MIN_SEG = 2.0
    merged: list = []
    for seg in segs:
        d = seg["end"] - seg["start"]
        if d < MIN_SEG and merged:
            merged[-1] = {**merged[-1], "end": seg["end"]}
        else:
            merged.append(dict(seg))

    if len({s["speed"] for s in merged}) <= 1:
        return False  # uniform speed – nothing to do

    n = len(merged)
    filter_parts, concat_parts = [], []
    for i, seg in enumerate(merged):
        s  = round(seg["start"], 3)
        d  = round(seg["end"] - seg["start"], 3)
        sp = seg["speed"]
        filter_parts.append(
            f"[0:v]trim=start={s}:duration={d},setpts=(PTS-STARTPTS)/{sp}[v{i}]"
        )
        filter_parts.append(
            f"[0:a]atrim=start={s}:duration={d},asetpts=(PTS-STARTPTS),atempo={sp}[a{i}]"
        )
        concat_parts.append(f"[v{i}][a{i}]")
    filter_parts.append(
        "".join(concat_parts) + f"concat=n={n}:v=1:a=1[vout][aout]"
    )
    cmd = [
        "ffmpeg", "-i", str(clip_path),
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-y", str(output),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        if r.returncode != 0:
            print(f"[SpeedRamp] failed: {r.stderr.decode(errors='replace')[-400:]}", flush=True)
        return r.returncode == 0
    except Exception as e:
        print(f"[SpeedRamp] exception: {e}", flush=True)
        return False


def apply_logo_overlay(clip_path: Path, logo_path: Path, cfg: dict, output: Path) -> bool:
    """Overlay a brand logo at specified corner, size and opacity."""
    corner  = cfg.get("corner", "br")
    opacity = max(0.1, min(1.0, float(cfg.get("opacity", 0.8))))
    size    = {"small": 80, "medium": 120, "large": 180}.get(cfg.get("size", "medium"), 120)
    pos = {
        "tl": ("20",       "20"),
        "tr": ("W-w-20",   "20"),
        "bl": ("20",       "H-h-20"),
        "br": ("W-w-20",   "H-h-20"),
    }
    x, y = pos.get(corner, ("W-w-20", "H-h-20"))
    cmd = [
        "ffmpeg", "-i", str(clip_path), "-i", str(logo_path),
        "-filter_complex",
        f"[1:v]scale={size}:-1,format=rgba,colorchannelmixer=aa={opacity}[logo];"
        f"[0:v][logo]overlay={x}:{y}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "copy", "-y", str(output),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        return r.returncode == 0
    except Exception as e:
        print(f"[Logo] overlay failed: {e}", flush=True)
        return False


# ── Thumbnail Generator ───────────────────────────────────────────────────────
_THUMB_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _thumb_peak_time(clip_path: Path, dur: float) -> float:
    """Return the timestamp of the highest-energy audio moment in the clip."""
    try:
        energies = extract_audio_energy(clip_path, dur)
        if energies:
            peak_t, _ = max(energies, key=lambda x: x[1])
            return round(max(0.5, min(peak_t, dur - 0.5)), 2)
    except Exception:
        pass
    return round(max(0.5, dur * 0.25), 2)


def _wrap_text(text: str, max_chars: int = 22) -> list:
    """Wrap text into lines of at most max_chars characters."""
    words = text.split()
    lines: list = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= max_chars:
            cur = (cur + " " + w).strip() if cur else w
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3]


def _esc_drawtext(s: str) -> str:
    """Escape a string for ffmpeg drawtext."""
    return (s.replace("\\", "\\\\")
             .replace("'",  "\\'")
             .replace(":",  "\\:")
             .replace("%",  "\\%")
             .replace("[",  "\\[")
             .replace("]",  "\\]"))


def _build_thumb_prompt(hooks: list, transcript: str) -> str:
    """Build a YouTube-thumbnail AI image prompt from video content analysis."""
    import re as _re
    clean = lambda s: _re.sub(r"[^\w\s\.,!?\-]", "", s).strip()

    if hooks:
        topic = clean(str(hooks[0]))[:80]
        return (
            f"YouTube Shorts thumbnail, ultra-realistic cinematic photo, "
            f"dramatic studio lighting, vivid saturated colors, high contrast, "
            f"dynamic composition, topic: {topic}, no text overlay, 4K sharp"
        )

    if transcript:
        kw = " ".join(clean(transcript).split()[:15])
        return (
            f"YouTube Shorts thumbnail, ultra-realistic cinematic photo, "
            f"dramatic lighting, vivid saturated colors, {kw}, no text, 4K sharp"
        )

    return (
        "YouTube Shorts thumbnail, ultra-realistic cinematic photo, "
        "dramatic lighting, vivid saturated colors, dynamic composition, "
        "no text overlay, 4K sharp"
    )


def _pollinations_generate(prompt: str, output_path: Path,
                           width: int = 720, height: int = 1280) -> bool:
    """Download an AI-generated image from Pollinations.ai (free, no key)."""
    import urllib.request
    import urllib.parse
    import random

    seed = random.randint(1, 99999)
    enc  = urllib.parse.quote(prompt, safe="")
    url  = (
        f"https://image.pollinations.ai/prompt/{enc}"
        f"?width={width}&height={height}&nologo=true&seed={seed}&enhance=true"
    )
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=55) as resp:
                data = resp.read()
            if len(data) < 5_000:
                print(f"[Thumb/AI] response too small ({len(data)} B)", flush=True)
                return False
            with open(str(output_path), "wb") as f:
                f.write(data)
            print(f"[Thumb/AI] {len(data)//1024} KB → {output_path.name}", flush=True)
            return True
        except Exception as e:
            print(f"[Thumb/AI] Pollinations attempt {attempt+1} failed: {e}", flush=True)
    return False


# ── Smart 4K Thumbnail (on-demand) ────────────────────────────────────────────

def _find_scene_timestamps(clip_path: Path, dur: float, n: int = 6) -> list:
    """Use ffmpeg scene-change detection to find visually distinct timestamps."""
    import re as _re
    cmd = [
        'ffmpeg', '-i', str(clip_path),
        '-vf', 'select=gt(scene\\,0.25),showinfo',
        '-vsync', '0', '-f', 'null', '-',
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    pts_times = []
    for m in _re.finditer(r'pts_time:(\d+\.?\d*)', r.stderr.decode(errors='replace')):
        t = float(m.group(1))
        if 0.5 < t < dur - 0.5:
            pts_times.append(round(t, 2))
    if pts_times:
        step = max(1, len(pts_times) // n)
        return pts_times[::step][:n]
    return [round(dur * k / (n + 1), 2) for k in range(1, n + 1)]


def _score_frame_sharpness(clip_path: Path, timestamp: float) -> float:
    """Score a frame's sharpness (higher = crisper) via ffmpeg blurdetect."""
    import re as _re
    cmd = [
        'ffmpeg', '-ss', str(timestamp), '-i', str(clip_path),
        '-vframes', '1', '-vf', 'blurdetect=high=0.01',
        '-f', 'null', '-',
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=10)
    m = _re.search(r'blur:(\d+\.?\d*)', r.stderr.decode(errors='replace'))
    if m:
        return 1.0 / (float(m.group(1)) + 0.01)   # lower blur → higher score
    return 0.5


def _build_4k_thumb_prompt(transcript: str) -> str:
    """Build a YouTube-optimised 4K thumbnail prompt from transcript keywords."""
    import re as _re
    from collections import Counter
    clean = lambda s: _re.sub(r"[^\w\s]", " ", s).strip()
    stopwords = {
        'that','this','with','have','from','they','will','been','were','when',
        'what','your','about','there','their','would','could','should','really',
        'just','like','very','more','some','only','then','than','into','over',
    }
    topic = 'viral trending content'
    if transcript:
        words = clean(transcript).split()
        meaningful = [w.lower() for w in words if len(w) > 4 and w.lower() not in stopwords]
        freq = Counter(meaningful)
        top = [w for w, _ in freq.most_common(6)]
        if top:
            topic = ', '.join(top)
    return (
        f"professional YouTube thumbnail, ultra-sharp 4K cinematic photo, "
        f"dramatic studio lighting with vivid rim lights, maximum color saturation, "
        f"ultra-high contrast, razor-sharp focus, shallow depth of field bokeh, "
        f"subject: {topic}, explosive visual impact, no text, no watermarks, "
        f"award-winning commercial photography, Getty Images quality, "
        f"16:9 widescreen, hyper-detailed"
    )


def generate_smart_thumbnail_4k(clip_path: Path) -> "Path | None":
    """Generate a 1920×1080 AI-powered thumbnail from deep video analysis.

    Pipeline
    --------
    1. Scene detection  → candidate timestamps
    2. Sharpness scoring → pick best visual frame
    3. Transcript load  → semantic keyword extraction
    4. Pollinations.ai  → 1280×720 AI image
    5. FFmpeg upscale   → 1920×1080 lanczos + unsharp + colour boost
    6. Fallback         → enhanced real frame if AI unavailable
    """
    out_path = CLIPS_DIR / f"{clip_path.stem}_thumb4k.jpg"
    if out_path.exists():          # serve cached
        return out_path

    try:
        dur, _, _ = get_video_info(clip_path)
    except Exception:
        return None

    # ── 1. Scene timestamps ─────────────────────────────────────────────────
    print(f"[Thumb4K] Analysing {clip_path.name} ({dur:.1f}s)…", flush=True)
    candidates = _find_scene_timestamps(clip_path, dur, n=6)

    # ── 2. Sharpness scoring ────────────────────────────────────────────────
    audio_t = _thumb_peak_time(clip_path, dur)
    best_t  = audio_t
    if candidates:
        scored = [(t, _score_frame_sharpness(clip_path, t)) for t in candidates]
        print(f"[Thumb4K] Frame scores: {[(t, round(s,3)) for t,s in scored]}", flush=True)
        visual_t = max(scored, key=lambda x: x[1])[0]
        best_t   = round(visual_t * 0.75 + audio_t * 0.25, 2)
    print(f"[Thumb4K] Best frame @{best_t}s", flush=True)

    # ── 3. Transcript keywords ──────────────────────────────────────────────
    words      = _load_words(clip_path.name)
    transcript = ' '.join(w.get('word', '') for w in words)
    prompt     = _build_4k_thumb_prompt(transcript)
    print(f"[Thumb4K] Prompt: {prompt[:90]}…", flush=True)

    # ── 4. AI generation (1280×720) ─────────────────────────────────────────
    ai_tmp = CLIPS_DIR / f"ai4k_{clip_path.stem}.jpg"
    ai_ok  = _pollinations_generate(prompt, ai_tmp, width=1280, height=720)

    if ai_ok:
        # ── 5. Upscale to 1920×1080 ─────────────────────────────────────────
        cmd = [
            'ffmpeg', '-i', str(ai_tmp),
            '-vf', (
                'scale=1920:1080:flags=lanczos,'
                'unsharp=5:5:1.2:5:5:0.0,'
                'eq=contrast=1.08:saturation=1.15:brightness=0.02'
            ),
            '-q:v', '1', '-y', str(out_path),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        try: ai_tmp.unlink(missing_ok=True)
        except: pass
        if r.returncode == 0 and out_path.exists():
            print(f"[Thumb4K] ✓ AI 1920×1080 → {out_path.name} ({out_path.stat().st_size//1024}KB)", flush=True)
            return out_path

    # ── 6. Fallback: best real frame, enhanced + upscaled ──────────────────
    print("[Thumb4K] AI unavailable, using enhanced frame fallback", flush=True)
    cmd = [
        'ffmpeg', '-ss', str(best_t), '-i', str(clip_path),
        '-vframes', '1',
        '-vf', (
            'scale=1920:1080:flags=lanczos,'
            'eq=contrast=1.22:saturation=1.55:brightness=0.04:gamma=0.92,'
            'unsharp=5:5:1.0:5:5:0.0'
        ),
        '-q:v', '1', '-y', str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=20)
    if r.returncode == 0 and out_path.exists():
        print(f"[Thumb4K] ✓ Frame fallback → {out_path.name}", flush=True)
        return out_path

    return None


def _apply_text_overlay(src: Path, dst: Path, hook_raw: str,
                        vid_w: int, vid_h: int) -> bool:
    """Burn hook text onto src image → dst using ffmpeg drawtext."""
    lines     = _wrap_text(hook_raw, max_chars=24)
    font_size = 54 if len(lines) <= 2 else 44
    line_gap  = font_size + 10
    bar_h     = 50 + len(lines) * line_gap
    fp_esc    = _THUMB_FONT.replace(":", "\\:")

    vf = [
        f"scale={vid_w}:{vid_h}:flags=lanczos",
        f"drawbox=x=0:y=ih-{bar_h}:w=iw:h={bar_h}:color=black@0.72:t=fill",
    ]
    for i, line in enumerate(reversed(lines)):
        y_off = 28 + i * line_gap
        vf.append(
            f"drawtext=fontfile='{fp_esc}':"
            f"text='{_esc_drawtext(line)}':"
            f"fontsize={font_size}:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-text_h-{y_off}:"
            f"shadowcolor=black@0.90:shadowx=2:shadowy=2:"
            f"borderw=2:bordercolor=black@0.70"
        )

    cmd = [
        "ffmpeg", "-i", str(src),
        "-vf", ",".join(vf),
        "-q:v", "2", "-y", str(dst),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        return r.returncode == 0 and dst.exists()
    except Exception:
        return False


def generate_thumbnail(clip_path: Path,
                       hooks: list = None,
                       transcript: str = "") -> "Path | None":
    """Generate a YouTube-style thumbnail.

    Pipeline
    --------
    1. Analyse   – locate peak-energy frame via audio RMS scan
    2. AI image  – call Pollinations.ai to generate a scene-matched background
    3. Overlay   – burn viral-hook text onto the AI image
    4. Fallback  – if AI fails, extract & enhance a real frame from the clip
    """
    import re as _re

    try:
        dur, vid_w, vid_h = get_video_info(clip_path)
    except Exception:
        return None

    best_t     = _thumb_peak_time(clip_path, dur)
    thumb_path = CLIPS_DIR / f"{clip_path.stem}_thumb.jpg"

    # ── Clean hook text for overlay ────────────────────────────────────────
    hook_raw = ""
    if hooks:
        hook_raw = _re.sub(r"[^\w\s\.,!?\-\'\"#@]", "", str(hooks[0])).strip()

    # ── Step 1: try Pollinations.ai AI generation ──────────────────────────
    ai_tmp = CLIPS_DIR / f"ai_thumb_{clip_path.stem}.jpg"
    prompt = _build_thumb_prompt(hooks, transcript)
    ai_ok  = _pollinations_generate(prompt, ai_tmp, width=vid_w, height=vid_h)

    if ai_ok:
        if hook_raw and Path(_THUMB_FONT).exists():
            overlay_ok = _apply_text_overlay(ai_tmp, thumb_path, hook_raw, vid_w, vid_h)
            try: ai_tmp.unlink(missing_ok=True)
            except: pass
            if overlay_ok:
                print(f"[Thumb] AI+text → {thumb_path.name}", flush=True)
                return thumb_path
            # text overlay failed – use plain AI image
            try: ai_tmp.rename(thumb_path)
            except: pass
        else:
            try: ai_tmp.rename(thumb_path)
            except: pass
        if thumb_path.exists():
            print(f"[Thumb] AI (no text) → {thumb_path.name}", flush=True)
            return thumb_path

    # ── Step 2: fallback – enhanced real frame ────────────────────────────
    print("[Thumb] AI failed, falling back to frame extraction", flush=True)
    vf_parts = [
        f"scale={vid_w}:{vid_h}:flags=lanczos",
        "eq=contrast=1.18:saturation=1.40:brightness=0.03:gamma=0.95",
    ]
    if hook_raw and Path(_THUMB_FONT).exists():
        lines     = _wrap_text(hook_raw, max_chars=24)
        fs        = 54 if len(lines) <= 2 else 44
        lg        = fs + 10
        bh        = 50 + len(lines) * lg
        fp_esc    = _THUMB_FONT.replace(":", "\\:")
        vf_parts.append(
            f"drawbox=x=0:y=ih-{bh}:w=iw:h={bh}:color=black@0.70:t=fill"
        )
        for i, line in enumerate(reversed(lines)):
            vf_parts.append(
                f"drawtext=fontfile='{fp_esc}':"
                f"text='{_esc_drawtext(line)}':"
                f"fontsize={fs}:fontcolor=white:"
                f"x=(w-text_w)/2:y=h-text_h-{28+i*lg}:"
                f"shadowcolor=black@0.90:shadowx=2:shadowy=2:"
                f"borderw=2:bordercolor=black@0.70"
            )

    cmd = [
        "ffmpeg", "-ss", str(best_t), "-i", str(clip_path),
        "-vframes", "1", "-vf", ",".join(vf_parts),
        "-q:v", "2", "-y", str(thumb_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        if r.returncode == 0 and thumb_path.exists():
            return thumb_path
    except Exception:
        pass

    # bare-minimum fallback
    try:
        r2 = subprocess.run(
            ["ffmpeg", "-ss", str(best_t), "-i", str(clip_path),
             "-vframes", "1", "-q:v", "2", "-y", str(thumb_path)],
            capture_output=True, timeout=15,
        )
        if r2.returncode == 0 and thumb_path.exists():
            return thumb_path
    except Exception:
        pass

    return None


# ── Step 7: Cut clip and Burn Subtitles ───────────────────────────────────────
def cut_clip(video_path: Path, start: float, end: float,
             idx: int, width: int, height: int, clip_duration: int,
             mode: str = "fill", captions_enabled: bool = True,
             caption_style: str = "mrbeast", language: str = None,
             audio_enhance: bool = False, custom_style_cfg: dict = None,
             color_grade: str = "none", auto_zoom: bool = False,
             emoji_burst: bool = False, logo_config: dict = None,
             face_focus: bool = False, speed_ramp: bool = False):
    name = f"short_{idx + 1}_{uuid.uuid4().hex[:6]}.mp4"
    out  = CLIPS_DIR / name
    temp_out = CLIPS_DIR / f"temp_{name}"

    if mode == "pad":
        vf = build_vf_pad(width, height)
    elif face_focus:
        vf = build_face_tracking_vf(video_path, start, end - start, width, height)
    else:
        vf = build_vf(width, height)
    cg_filter = COLOR_GRADE_FILTERS.get(color_grade or "none", "")
    if cg_filter:
        vf = vf + "," + cg_filter
    dur = round(end - start, 2)

    # ── Save raw (pre-enhancement) audio segment for before/after preview ─────
    raw_audio_out = CLIPS_DIR / f"{out.stem}_raw.mp3"
    if audio_enhance:
        subprocess.run([
            "ffmpeg", "-ss", str(start), "-i", str(video_path),
            "-t", str(dur), "-vn", "-acodec", "libmp3lame", "-q:a", "5",
            "-y", str(raw_audio_out)
        ], capture_output=True)

    # ── Build audio filter chain (Segment 3 – Audio Enhancement) ─────────────
    audio_af = []
    if audio_enhance:
        audio_af = [
            # 1. Remove low-frequency rumble (AC, HVAC, mic handling noise)
            "highpass=f=80",
            # 2. Gentle adaptive FFT noise reduction (background hiss/hum)
            "afftdn=nf=-25",
            # 3. Cut muddiness in the 200-300 Hz range (boxy, honky resonance)
            #    width_type=q uses Q-factor (0.7 = 1.4 octaves) — avoids Nyquist overflow
            "equalizer=f=250:width_type=q:width=0.7:g=-3",
            # 4. Boost voice presence / clarity (2-5 kHz — the "intelligibility" band)
            "equalizer=f=3500:width_type=q:width=0.8:g=4",
            # 5. Add subtle air / sparkle above 8 kHz for crisp consonants
            #    treble filter is simpler and safe at high frequencies
            "treble=g=2:f=8000",
            # 6. Dynamic compression — keeps quiet words audible, tames peaks
            "acompressor=threshold=0.125:ratio=3:attack=5:release=60:makeup=2",
            # 7. Final loudness normalisation to broadcast standard (-14 LUFS)
            # linear=true → single-pass (fast); two-pass is too slow for real-time
            "loudnorm=I=-14:TP=-1.5:LRA=7:linear=true",
        ]

    base_cmd = [
        "ffmpeg", "-ss", str(start), "-i", str(video_path),
        "-t", str(dur), "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
    ]
    if audio_af:
        base_cmd += ["-af", ",".join(audio_af), "-c:a", "aac", "-b:a", "192k"]
    else:
        base_cmd += ["-c:a", "aac", "-b:a", "128k"]
    base_cmd += ["-y", str(temp_out)]

    # 1) Export cropped + enhanced portion (without subtitles)
    try:
        r1 = subprocess.run(base_cmd, capture_output=True, timeout=240)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"FFmpeg crop timed out for clip {idx + 1} (>240s)")
    if r1.returncode != 0:
        raise RuntimeError(f"FFmpeg crop failed for clip {idx + 1}: {r1.stderr.decode(errors='replace')[-600:]}")

    transcript = ""
    if captions_enabled:
        # 2) Transcribe + generate ASS
        try:
            ass_path, transcript = transcribe_and_generate_ass(
                temp_out, caption_style, language=language, custom_cfg=custom_style_cfg
            )
            # Rename SRT to match final output filename
            srt_src = temp_out.with_suffix(".srt")
            srt_dst = out.with_suffix(".srt")
            if srt_src.exists():
                srt_src.rename(srt_dst)
            # Re-key transcript storage under final name
            with _transcripts_lock:
                if temp_out.name in _transcripts:
                    _transcripts[name] = _transcripts.pop(temp_out.name)
            # Rename .words.json sidecar to match final clip name
            old_json = _words_json_path(temp_out.name)
            new_json = _words_json_path(name)
            if old_json.exists():
                try:
                    old_json.rename(new_json)
                except Exception:
                    pass
        except Exception as e:
            print(f"[*] Whisper annotation failed: {e}")
            temp_out.rename(out)
            return out, transcript

        # 3) Burn ASS captions + emoji burst overlays (single pass)
        escaped_ass = str(ass_path.absolute()).replace("\\", "/").replace(":", "\\:")
        emoji_filters: list = []
        if emoji_burst:
            clip_words = _load_words(name) or _load_words(temp_out.name)
            emoji_filters = build_emoji_overlays(clip_words, dur)
        caption_vf = f"ass='{escaped_ass}'"
        if emoji_filters:
            caption_vf = caption_vf + "," + ",".join(emoji_filters)
        try:
            r2 = subprocess.run(
                [
                    "ffmpeg", "-i", str(temp_out),
                    "-vf", caption_vf,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                    "-c:a", "copy", "-movflags", "+faststart",
                    "-y", str(out),
                ],
                capture_output=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"FFmpeg caption burn timed out for clip {idx + 1} (>180s)")

        # Keep ASS alongside final clip for alpha-channel export
        kept_ass = out.with_suffix(".ass")
        if ass_path.exists():
            try:
                shutil.copy2(str(ass_path), str(kept_ass))
                ass_path.unlink()
            except Exception:
                pass
        # Clean up temp clip
        if temp_out.exists():
            try: temp_out.unlink()
            except: pass

        if r2.returncode != 0:
            raise RuntimeError(f"FFmpeg caption failed for clip {idx + 1}: {r2.stderr.decode(errors='replace')[-600:]}")
    else:
        if temp_out.exists():
            temp_out.rename(out)

    # ── Speed Ramp post-process ───────────────────────────────────────────────
    if speed_ramp and out.exists():
        ramp_tmp = CLIPS_DIR / f"ramp_{uuid.uuid4().hex[:6]}.mp4"
        if apply_speed_ramp(out, ramp_tmp):
            try:
                ramp_tmp.replace(out)
            except Exception:
                try: ramp_tmp.unlink(missing_ok=True)
                except: pass

    # ── Auto-Zoom post-process ────────────────────────────────────────────────
    if auto_zoom and out.exists():
        zoom_tmp = CLIPS_DIR / f"zoom_{uuid.uuid4().hex[:6]}.mp4"
        if apply_auto_zoom(out, zoom_tmp):
            try:
                zoom_tmp.replace(out)
            except Exception:
                try: zoom_tmp.unlink(missing_ok=True)
                except: pass

    # ── Logo Overlay post-process ─────────────────────────────────────────────
    if logo_config and out.exists():
        logo_file = (logo_config.get("filename") or "").strip()
        logo_path = LOGOS_DIR / logo_file if logo_file else None
        if logo_path and logo_path.exists():
            logo_tmp = CLIPS_DIR / f"logo_{uuid.uuid4().hex[:6]}.mp4"
            if apply_logo_overlay(out, logo_path, logo_config, logo_tmp):
                try:
                    logo_tmp.replace(out)
                except Exception:
                    try: logo_tmp.unlink(missing_ok=True)
                    except: pass

    return out, transcript

# ── Viral Hooks Generator ─────────────────────────────────────────────────────
def generate_viral_hooks(transcript: str, api_key: str) -> list:
    import urllib.request
    import urllib.error
    import json
    if not transcript or not api_key:
        print(f"[*] Viral Hooks skipped: transcript={'empty' if not transcript else 'ok'}, key={'missing' if not api_key else 'ok'}", flush=True)
        return []
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    prompt = (
        "Analyze the following short video transcript and write 3 highly engaging, viral TikTok/Shorts "
        "hooks or on-screen text titles that would capture a viewer's attention instantly. "
        "Return ONLY a raw JSON array of exactly 3 strings. Do NOT include any markdown, code fences, "
        "explanation, or any text outside the JSON array itself.\n\n"
        f"Transcript: {transcript}"
    )
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8,
        "max_tokens": 300,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "groq-python/1.0.0",
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            resp_body = response.read().decode("utf-8")
            resp_json = json.loads(resp_body)
            # OpenAI-compatible response format
            text = resp_json["choices"][0]["message"]["content"].strip()
            print(f"[*] Groq raw response: {text[:200]}", flush=True)
            # strip markdown fences if the model adds them
            if text.startswith("```json"):
                text = text[7:]
                text = text[:text.rfind("```")].strip()
            elif text.startswith("```"):
                text = text[3:]
                text = text[:text.rfind("```")].strip()
                
            hooks = json.loads(text)
            if isinstance(hooks, list):
                print(f"[OK] Generated {len(hooks)} viral hooks", flush=True)
                return hooks[:3]
    except urllib.error.HTTPError as e:
        # Read the body so we know the actual error (e.g. invalid API key)
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"[!] Groq API HTTP {e.code} error: {error_body[:500]}", flush=True)
    except urllib.error.URLError as e:
        print(f"[!] Groq API connection error: {e.reason}", flush=True)
    except json.JSONDecodeError as e:
        print(f"[!] Groq response JSON parse error: {e}", flush=True)
    except Exception as e:
        print(f"[!] Groq unexpected error: {e}", flush=True)
        
    return []

# ── B-Roll Generator (Pollinations.ai, free) ─────────────────────────────────

def _build_broll_prompt(segment_text: str) -> str:
    """Build a Pollinations.ai prompt from a transcript segment."""
    snippet = ' '.join(segment_text.split()[:10]).strip('.,!?;:')
    return (
        f"cinematic vertical 9:16 B-roll footage, {snippet}, "
        "4K quality, dramatic lighting, bokeh, no faces, "
        "no text, no watermarks, photorealistic, professional photography"
    )

def extract_broll_moments(words: list, clip_duration: float, max_brolls: int = 3) -> list:
    """Identify 2-3 timestamps that would benefit from B-roll visuals.
    Returns [{'start': float, 'duration': float, 'prompt': str}]"""
    if clip_duration < 8:
        return []

    # Fallback: time-based slots when no transcript words available
    if not words:
        moments = []
        slot_dur = min(4.0, clip_duration * 0.25)
        step = clip_duration / (max_brolls + 1)
        for k in range(1, max_brolls + 1):
            t = round(step * k, 2)
            if t + slot_dur < clip_duration - 1.0:
                moments.append({
                    'start':    round(t, 2),
                    'duration': round(slot_dur, 2),
                    'prompt':   'cinematic vertical 9:16 B-roll, dramatic lighting, bokeh, no faces, no text, photorealistic',
                })
        return moments

    segments = []
    seg_start = words[0].get('start', 0)
    seg_words = []
    for w in words:
        seg_words.append(w.get('word', ''))
        t_end = w.get('end', 0)
        if t_end - seg_start >= 6.0:
            segments.append((seg_start, t_end, ' '.join(seg_words)))
            seg_start = t_end
            seg_words = []
    if seg_words:
        t_end = words[-1].get('end', 0)
        segments.append((seg_start, t_end, ' '.join(seg_words)))

    moments = []
    for seg_start, seg_end, text in segments:
        # Only skip first second and last second — was too aggressive at 4s/2s
        if seg_start < 1.0 or seg_end > clip_duration - 1.0:
            continue
        seg_len = seg_end - seg_start
        if seg_len < 3.5:
            continue
        moments.append({
            'start':    round(seg_start + 0.2, 2),
            'duration': round(min(5.0, seg_len * 0.6), 2),
            'prompt':   _build_broll_prompt(text),
        })
        if len(moments) >= max_brolls:
            break
    return moments

def download_broll_image(prompt: str, idx: int) -> "Path | None":
    """Download an AI-generated image from Pollinations.ai (free, no API key).
    Uses 540x960 (half res) for faster generation; retries once on timeout."""
    import urllib.request as ureq
    import urllib.parse
    import random
    encoded = urllib.parse.quote(prompt, safe='')
    seed = random.randint(1000, 99999)
    # 540x960 is 9:16 and generates 3-4x faster than 1080x1920 on Pollinations
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=540&height=960&nologo=true&seed={seed}"
    )
    out_path = CLIPS_DIR / f"broll_img_{uuid.uuid4().hex[:8]}.jpg"
    for attempt in range(2):
        try:
            print(f"[BRoll] Fetching image {idx+1} (attempt {attempt+1}): {prompt[:60]}…", flush=True)
            req = ureq.Request(url, headers={'User-Agent': 'Voxly/1.0'})
            with ureq.urlopen(req, timeout=55) as resp:
                data = resp.read()
            if len(data) < 2000:
                print(f"[BRoll] Image {idx+1} too small ({len(data)} bytes), skipping", flush=True)
                return None
            out_path.write_bytes(data)
            print(f"[BRoll] Downloaded image {idx+1} ({len(data)//1024} KB)", flush=True)
            return out_path
        except Exception as e:
            print(f"[BRoll] Image download attempt {attempt+1} failed (idx={idx}): {e}", flush=True)
    return None

def image_to_video(image_path: Path, duration: float, output_path: Path) -> bool:
    """Convert a still image to a video clip (fast static encode, no zoompan)."""
    cmd = [
        'ffmpeg', '-loop', '1', '-i', str(image_path),
        '-vf', (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "fps=30"
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
        print(f"[BRoll] image_to_video failed: {e}", flush=True)
        return False

def apply_brolls_to_clip(main_clip: Path, brolls: list, output: Path) -> bool:
    """Splice B-roll clips into main clip at specified timestamps.
    Strategy: for each B-roll window, cut that segment from main video and
    replace with the B-roll visual while keeping the original audio throughout.
    Uses setpts/overlay without alpha so it works on every ffmpeg build."""
    if not brolls:
        return False
    n = len(brolls)
    # Build inputs: main clip first, then each B-roll video
    cmd = ['ffmpeg', '-i', str(main_clip)]
    for b in brolls:
        cmd += ['-i', b['video_path']]

    # filter_complex:
    #   1. Scale each B-roll to 1080x1920
    #   2. For each B-roll, overlay onto main video during its time window
    #      using 'enable' expression — no alpha needed, direct cut-in
    filter_parts = []
    for i, b in enumerate(brolls):
        filter_parts.append(
            f"[{i+1}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,setsar=1,format=yuv420p[bv{i}]"
        )

    prev = "[0:v]"
    for i, b in enumerate(brolls):
        s = round(b['start'], 3)
        e = round(b['start'] + b['duration'], 3)
        out_label = f"[ov{i}]" if i < n - 1 else "[vout]"
        # overlay the B-roll on top of main during time window; outside window
        # the B-roll is positioned off-screen (x=9999) so main video shows
        filter_parts.append(
            f"{prev}[bv{i}]overlay="
            f"x='if(between(t,{s},{e}),0,9999)':y=0:shortest=1{out_label}"
        )
        prev = f"[ov{i}]"

    cmd += [
        '-filter_complex', ';'.join(filter_parts),
        '-map', '[vout]', '-map', '0:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
        '-c:a', 'copy', '-movflags', '+faststart',
        '-y', str(output),
    ]
    print(f"[BRoll] Running apply_brolls ffmpeg ({n} b-rolls)…", flush=True)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        if r.returncode != 0:
            err = r.stderr.decode(errors='replace')
            print(f"[BRoll] apply failed (rc={r.returncode}): {err[-600:]}", flush=True)
        else:
            print(f"[BRoll] apply_brolls succeeded → {output.name}", flush=True)
        return r.returncode == 0
    except Exception as e:
        print(f"[BRoll] apply exception: {e}", flush=True)
        return False

def calculate_viral_score(transcript: str, clip_duration: float,
                           caption_style: str, broll_count: int) -> float:
    """Score 1–10 representing the viral potential of a generated Short."""
    score = 4.0
    # Duration sweet spot (28-62 s is ideal for Shorts)
    if 28 <= clip_duration <= 62:
        score += 1.0
    elif 15 <= clip_duration < 28 or 62 < clip_duration <= 90:
        score += 0.4
    # Speaking pace
    if transcript and clip_duration > 0:
        wpm = len(transcript.split()) / (clip_duration / 60)
        if 120 <= wpm <= 200:
            score += 0.7
        elif 80 <= wpm < 120 or 200 < wpm <= 250:
            score += 0.3
    # Hook keywords in first 30 words
    HOOK = {
        'shocking','secret','truth','revealed','exposed','incredible','insane',
        'crazy','unbelievable','never','always','mistake','wrong','stop',
        'biggest','warning','must','need','hack','trick','strategy','proven',
        'rich','money','free','fast','easy','nobody','everyone','why','how',
        'best','worst','only','actually','honestly','literally','finally',
    }
    if transcript:
        hits = len(set(transcript.lower().split()[:30]) & HOOK)
        score += min(1.0, hits * 0.5)
    # B-rolls add visual variety
    score += min(1.5, broll_count * 0.5)
    # Animated caption styles
    if caption_style in {'mrbeast','hormozi','tiktok','garyvee','imangadzi','devinjatho'}:
        score += 0.4
    # Content density
    if transcript and len(transcript.split()) >= 60:
        score += 0.3
    return round(min(10.0, max(1.0, score)), 1)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/api/process", methods=["POST"])
def process():
    data        = request.get_json(force=True, silent=True) or {}
    youtube_url = (data.get("youtubeUrl") or "").strip()
    gemini_key  = (data.get("geminiKey") or "").strip()

    # Segment 1 – source: youtube URL or uploaded file
    source_type   = data.get("sourceType", "youtube")  # "youtube" | "upload"
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
    # Segment 1 – language
    lang_name         = (data.get("language") or "english").strip().lower()
    language          = LANGUAGE_CODES.get(lang_name, "en")
    # Segment 3 – audio enhancement
    audio_enhance     = bool(data.get("audioEnhance", False))
    # Segment 5 – custom caption style
    custom_style_cfg  = data.get("customStyle") or None
    # B-Roll AI generation
    broll_enabled     = bool(data.get("brollEnabled", False))
    # Visual enhancements
    color_grade       = (data.get("colorGrade") or "none").strip()
    auto_zoom         = bool(data.get("autoZoom", False))
    emoji_burst       = bool(data.get("emojiBurst", False))
    logo_config       = data.get("logoConfig") or None
    face_focus        = bool(data.get("faceFocus", False))
    speed_ramp        = bool(data.get("speedRamp", False))

    if mode not in ("fill", "pad"):
        mode = "fill"

    video_id = _extract_video_id(youtube_url) if youtube_url else None

    def generate():
        video_path = None
        uploaded_temp = None
        try:
            if source_type == "upload":
                # Use uploaded file directly
                up_path = UPLOADS_DIR / upload_file
                if not up_path.exists():
                    yield json.dumps({"error": "Uploaded file not found. Please re-upload."}) + "\n"
                    return
                video_path = up_path
            else:
                video_path = download_video(youtube_url)

            duration, width, height = get_video_info(video_path)
            if duration < 20:
                yield json.dumps({"error": "Video too short (minimum 20 s)."}) + "\n"
                return
            if width == 0 or height == 0:
                yield json.dumps({"error": "Could not read video dimensions."}) + "\n"
                return

            segments = find_speech_dense_segments(
                video_path, duration, n_clips=n_clips,
                clip_duration=clip_duration, video_id=video_id, language=language
            )
            if not segments:
                yield json.dumps({"error": "No viable segments found."}) + "\n"
                return

            yield json.dumps({"total": len(segments)}) + "\n"

            def _cut(args):
                i, s, e = args
                clip_path, transcript = cut_clip(
                    video_path, s, e, i, width, height, clip_duration,
                    mode, captions_enabled, caption_style,
                    language=language, audio_enhance=audio_enhance,
                    custom_style_cfg=custom_style_cfg,
                    color_grade=color_grade, auto_zoom=auto_zoom,
                    emoji_burst=emoji_burst, logo_config=logo_config,
                    face_focus=face_focus, speed_ramp=speed_ramp,
                )
                hooks = []
                if gemini_key and transcript:
                    hooks = generate_viral_hooks(transcript, gemini_key)

                # ── B-Roll AI Generation ──────────────────────────────────
                broll_count = 0
                if broll_enabled:
                    dur = round(e - s, 2)
                    # Load words if available; extract_broll_moments handles
                    # empty words list with a time-based fallback automatically
                    words_for_broll = _load_words(clip_path.name)
                    moments = extract_broll_moments(words_for_broll, dur)
                    print(f"[BRoll] Clip {i+1}: dur={dur}s, words={len(words_for_broll)}, moments={len(moments)}", flush=True)
                    if moments:
                        print(f"[BRoll] Downloading {len(moments)} images for clip {i+1}…", flush=True)
                        broll_videos = []

                        def _fetch_and_encode(bi_m):
                            bi, m = bi_m
                            img = download_broll_image(m['prompt'], bi)
                            if not img:
                                return None
                            vid = img.with_suffix('.mp4')
                            ok = image_to_video(img, m['duration'], vid)
                            try: img.unlink(missing_ok=True)
                            except: pass
                            if ok:
                                return {'start': m['start'], 'duration': m['duration'], 'video_path': str(vid)}
                            print(f"[BRoll] image_to_video failed for moment {bi}", flush=True)
                            return None

                        with ThreadPoolExecutor(max_workers=min(len(moments), 3)) as bpool:
                            for result in bpool.map(_fetch_and_encode, enumerate(moments)):
                                if result:
                                    broll_videos.append(result)
                        print(f"[BRoll] {len(broll_videos)}/{len(moments)} images ready for clip {i+1}", flush=True)
                        if broll_videos:
                            brtmp = CLIPS_DIR / f"brtmp_{uuid.uuid4().hex[:6]}.mp4"
                            if apply_brolls_to_clip(clip_path, broll_videos, brtmp):
                                try:
                                    brtmp.replace(clip_path)
                                    broll_count = len(broll_videos)
                                    print(f"[BRoll] ✓ Applied {broll_count} B-rolls to clip {i+1}", flush=True)
                                except Exception as ex:
                                    print(f"[BRoll] replace failed: {ex}", flush=True)
                                    try: brtmp.unlink(missing_ok=True)
                                    except: pass
                            else:
                                try: brtmp.unlink(missing_ok=True)
                                except: pass
                            for bv in broll_videos:
                                try: Path(bv['video_path']).unlink(missing_ok=True)
                                except: pass

                viral_score = calculate_viral_score(
                    transcript, round(e - s, 2), caption_style, broll_count
                )
                has_raw   = (CLIPS_DIR / f"{clip_path.stem}_raw.mp3").exists()
                has_ass   = (CLIPS_DIR / f"{clip_path.stem}.ass").exists()
                return i, clip_path, hooks, has_raw, has_ass, viral_score, broll_count, transcript or ""

            # ── Phase 1: stream clips immediately as they finish ───────────────
            thumb_jobs: dict = {}  # idx -> (clip_path, hooks, transcript_txt)

            with ThreadPoolExecutor(max_workers=min(len(segments), 3)) as pool:
                futures = {pool.submit(_cut, (i, s, e)): i
                           for i, (s, e) in enumerate(segments)}
                for future in as_completed(futures):
                    try:
                        i, clip_path, hooks, has_raw, has_ass, viral_score, broll_count, tr_txt = future.result()
                        has_srt = clip_path.with_suffix(".srt").exists()
                        yield json.dumps({
                            "clip":         f"/clips/{clip_path.name}",
                            "index":        i,
                            "hooks":        hooks,
                            "hasSrt":       has_srt,
                            "hasRawAudio":  has_raw,
                            "hasAlpha":     has_ass,
                            "viralScore":   viral_score,
                            "brollCount":   broll_count,
                            "hasThumbnail": False,
                        }) + "\n"
                        thumb_jobs[i] = (clip_path, hooks, tr_txt)
                    except Exception as clip_err:
                        i = futures[future]
                        yield json.dumps({"warning": f"Clip {i + 1} failed: {clip_err}"}) + "\n"

            # ── Phase 2: generate thumbnails in background, stream updates ─────
            if thumb_jobs:
                with ThreadPoolExecutor(max_workers=3) as tpool:
                    tfutures = {
                        tpool.submit(generate_thumbnail, cp, h, tr): idx
                        for idx, (cp, h, tr) in thumb_jobs.items()
                    }
                    for tf in as_completed(tfutures):
                        idx = tfutures[tf]
                        try:
                            result = tf.result()
                            if result:
                                yield json.dumps({
                                    "thumbReady": True,
                                    "index": idx,
                                }) + "\n"
                        except Exception:
                            pass

        except Exception as exc:
            yield json.dumps({"error": str(exc)}) + "\n"

        finally:
            # Only delete downloaded YT files, keep uploaded files in place
            if source_type == "youtube" and video_path and video_path.exists():
                try:
                    video_path.unlink()
                except OSError:
                    pass

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={"X-Accel-Buffering": "no"},
    )


# ── Logo Upload ───────────────────────────────────────────────────────────────
@app.route("/api/upload-logo", methods=["POST"])
def upload_logo():
    """Accept a logo image for watermark overlay (PNG, JPG, WebP)."""
    if "file" not in request.files:
        return jsonify({"error": "No file field in request"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    allowed = {".png", ".jpg", ".jpeg", ".webp"}
    ext = Path(f.filename).suffix.lower()
    if ext not in allowed:
        return jsonify({"error": f"Unsupported format {ext}. Use PNG, JPG or WebP."}), 400
    safe_name = f"logo_{uuid.uuid4().hex[:8]}{ext}"
    dest = LOGOS_DIR / safe_name
    try:
        f.save(str(dest))
    except Exception as e:
        return jsonify({"error": f"Save failed: {e}"}), 500
    return jsonify({"ok": True, "filename": safe_name})


# ── Segment 1: Direct video file upload ──────────────────────────────────────
@app.route("/api/upload-video", methods=["POST"])
def upload_video():
    """Accept a direct video file upload (mp4, mov, mkv, webm, avi)."""
    if "file" not in request.files:
        return jsonify({"error": "No file field in request"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    allowed = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    ext = Path(f.filename).suffix.lower()
    if ext not in allowed:
        return jsonify({"error": f"Unsupported format {ext}. Use MP4, MOV, MKV, WEBM or AVI."}), 400

    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / safe_name
    try:
        f.save(str(dest))
    except Exception as e:
        return jsonify({"error": f"Save failed: {e}"}), 500

    # Quick sanity-check: confirm ffprobe can read it
    try:
        duration, width, height = get_video_info(dest)
        if duration < 5:
            dest.unlink(missing_ok=True)
            return jsonify({"error": "Video is too short (minimum 5 s)."}), 400
    except Exception:
        dest.unlink(missing_ok=True)
        return jsonify({"error": "Could not read video file. Is it a valid video?"}), 400

    return jsonify({
        "ok":       True,
        "filename": safe_name,
        "duration": duration,
        "width":    width,
        "height":   height,
    })


# ── Clip Trimmer ──────────────────────────────────────────────────────────────
@app.route("/api/trim-clip/<filename>")
def trim_clip(filename):
    """Re-encode a clip to the requested [start, end] window and stream back."""
    safe = Path(filename).name
    if not safe.endswith(".mp4"):
        return jsonify({"error": "Invalid file"}), 400
    clip_path = CLIPS_DIR / safe
    if not clip_path.exists():
        return jsonify({"error": "Clip not found"}), 404
    try:
        t_start = round(float(request.args.get("start", 0)), 3)
        t_end   = round(float(request.args.get("end",   0)), 3)
    except ValueError:
        return jsonify({"error": "Invalid time parameters"}), 400
    if t_end <= t_start or t_start < 0:
        return jsonify({"error": "Invalid trim range"}), 400

    duration  = round(t_end - t_start, 3)
    out_path  = CLIPS_DIR / f"trim_{uuid.uuid4().hex[:8]}.mp4"
    cmd = [
        "ffmpeg", "-ss", str(t_start), "-i", str(clip_path),
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", str(out_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0:
            return jsonify({"error": "Trim failed"}), 500
        file_size = out_path.stat().st_size

        def stream_and_cleanup():
            try:
                with open(str(out_path), "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
            finally:
                try: out_path.unlink(missing_ok=True)
                except: pass

        return Response(
            stream_with_context(stream_and_cleanup()),
            mimetype="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="trimmed_{safe}"',
                "Content-Length": str(file_size),
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        try: out_path.unlink(missing_ok=True)
        except: pass
        return jsonify({"error": str(e)}), 500


# ── Segment 2: SRT export ─────────────────────────────────────────────────────
@app.route("/api/clip-srt/<filename>")
def get_clip_srt(filename):
    """Stream the .srt file for a generated clip."""
    srt_path = CLIPS_DIR / Path(filename).with_suffix(".srt").name
    if not srt_path.exists():
        # Try generating from stored transcript
        mp4_name = Path(filename).with_suffix(".mp4").name
        words = _load_words(mp4_name)
        if not words:
            return jsonify({"error": "SRT not available for this clip"}), 404
        srt_content = generate_srt_content(words)
        return Response(
            srt_content,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{Path(filename).stem}.srt"'},
        )
    return send_from_directory(
        str(CLIPS_DIR),
        srt_path.name,
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name=Path(filename).stem + ".srt",
    )


# ── Segment 4: Transcript for Caption Editor ──────────────────────────────────
@app.route("/api/clip-transcript/<filename>")
def get_clip_transcript(filename):
    """Return word-level transcript JSON for the Caption Editor."""
    mp4_name = Path(filename).with_suffix(".mp4").name
    words = _load_words(mp4_name)
    if not words:
        return jsonify({"error": "Transcript not available — captions may have been disabled."}), 404
    return jsonify({"words": words})


# ── Segment 4: Re-bake captions from edited transcript ────────────────────────
@app.route("/api/rebake-captions", methods=["POST"])
def rebake_captions():
    """
    Re-render a clip with an edited word list.
    Body: { filename, words: [{word, start, end}], captionStyle, customStyle }
    Returns: { clip: "/clips/<new_name>" }
    """
    data = request.get_json(force=True, silent=True) or {}
    filename     = (data.get("filename") or "").strip()
    words        = data.get("words") or []
    caption_style = data.get("captionStyle", "mrbeast")
    custom_cfg   = data.get("customStyle") or None

    if not filename or not words:
        return jsonify({"error": "filename and words are required"}), 400

    src = CLIPS_DIR / Path(filename).with_suffix(".mp4").name
    if not src.exists():
        return jsonify({"error": "Source clip not found"}), 404

    new_name = f"rebaked_{uuid.uuid4().hex[:8]}.mp4"
    out      = CLIPS_DIR / new_name
    srt_out  = out.with_suffix(".srt")
    ass_path = src.with_suffix(f"_{uuid.uuid4().hex[:4]}.ass")

    # Build ASS from edited words
    STYLE_CONFIGS_REBAKE = {
        "mrbeast":   {"font":"Impact","size":110,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H80000000","bold":-1,"outline_w":3,"shadow":2,"marginv":288,"chunk":3,"highlight":"&H0000FFFF","upper":True},
        "hormozi":   {"font":"Arial Black","size":105,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&HA0000000","bold":-1,"outline_w":2,"shadow":1,"marginv":240,"chunk":2,"highlight":"&H0014D4FF","upper":True},
        "garyvee":   {"font":"Arial Black","size":115,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H90000000","bold":-1,"outline_w":4,"shadow":0,"marginv":260,"chunk":2,"highlight":"&H002165FB","upper":True},
        "loganpaul": {"font":"Poppins","size":100,"primary":"&H00E2E8F0","outline":"&H00000000","back":"&H70000000","bold":-1,"outline_w":2,"shadow":3,"marginv":270,"chunk":3,"highlight":"&H00F8BD38","upper":True},
        "minimal":   {"font":"Inter","size":90,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H55000000","bold":0,"outline_w":0,"shadow":2,"marginv":260,"chunk":4,"highlight":"&H00CCCCCC","upper":False},
        "tiktok":    {"font":"Arial Black","size":112,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H80000000","bold":-1,"outline_w":3,"shadow":2,"marginv":280,"chunk":2,"highlight":"&H00FF2DD4","upper":True},
        "imangadzi": {"font":"Impact","size":108,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H88000000","bold":-1,"outline_w":3,"shadow":1,"marginv":270,"chunk":2,"highlight":"&H0022B4FF","upper":True},
        "devinjatho":{"font":"Arial Black","size":118,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H75000000","bold":-1,"outline_w":4,"shadow":0,"marginv":265,"chunk":2,"highlight":"&H0040E040","upper":True},
        "karaoke":   {"font":"Impact","size":108,"primary":"&H0000FFFF","outline":"&H00000000","back":"&H60000000","bold":-1,"outline_w":3,"shadow":1,"marginv":270,"chunk":4,"highlight":"&H0000FFFF","upper":True,"_karaoke":True},
        "outlined":  {"font":"Arial Black","size":106,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H00000000","bold":-1,"outline_w":8,"shadow":0,"marginv":272,"chunk":3,"highlight":"&H0040C0FF","upper":True},
        "gradient":  {"font":"Impact","size":108,"primary":"&H00FFFFFF","outline":"&H00000000","back":"&H70000000","bold":-1,"outline_w":3,"shadow":1,"marginv":270,"chunk":3,"highlight":"&H0000FFFF","upper":True,"_gradient":True},
    }

    def hex_to_ass_rb(h: str) -> str:
        h = h.lstrip("#")
        if len(h) == 6:
            r, g, b = h[0:2], h[2:4], h[4:6]
            return f"&H00{b}{g}{r}"
        return h

    cfg = dict(STYLE_CONFIGS_REBAKE.get(caption_style, STYLE_CONFIGS_REBAKE["mrbeast"]))
    if custom_cfg:
        if custom_cfg.get("font"):           cfg["font"]      = custom_cfg["font"]
        if custom_cfg.get("size"):           cfg["size"]      = int(custom_cfg["size"])
        if custom_cfg.get("primaryColor"):   cfg["primary"]   = hex_to_ass_rb(custom_cfg["primaryColor"])
        if custom_cfg.get("outlineColor"):   cfg["outline"]   = hex_to_ass_rb(custom_cfg["outlineColor"])
        if custom_cfg.get("highlightColor"):  cfg["highlight"] = hex_to_ass_rb(custom_cfg["highlightColor"])
        if custom_cfg.get("wordsPerLine"):   cfg["chunk"]     = int(custom_cfg["wordsPerLine"])
        if custom_cfg.get("position") == "top":    cfg["marginv"] = 80
        elif custom_cfg.get("position") == "center": cfg["marginv"] = 900

    ass_header = f"""[Script Info]\nScriptType: v4.00+\nCollisions: Normal\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{cfg['font']},{cfg['size']},{cfg['primary']},&H000000FF,{cfg['outline']},{cfg['back']},{cfg['bold']},0,0,0,100,100,0,0,1,{cfg['outline_w']},{cfg['shadow']},2,20,20,{cfg['marginv']},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""

    chunk_size = int(cfg["chunk"])
    upper      = bool(cfg["upper"])
    HL_TAG     = "{\\c" + cfg["highlight"] + "&}"
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

    try:
        ass_path.write_text(ass_header + "\n".join(events) + "\n", encoding="utf-8")
        escaped_ass = str(ass_path.absolute()).replace("\\", "/").replace(":", "\\:")
        r = subprocess.run(
            ["ffmpeg", "-i", str(src), "-vf", f"ass='{escaped_ass}'",
             "-c:v","libx264","-preset","ultrafast","-crf","26",
             "-c:a","copy","-movflags","+faststart","-y", str(out)],
            capture_output=True,
        )
        if r.returncode != 0:
            return jsonify({"error": "Re-bake failed: " + r.stderr.decode(errors="replace")[-400:]}), 500

        # Save new SRT + transcript
        srt_out.write_text(generate_srt_content(words), encoding="utf-8")
        _save_words(new_name, words)

        return jsonify({"clip": f"/clips/{new_name}", "ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if ass_path.exists():
            try: ass_path.unlink()
            except: pass


# ── Feature: Custom Font Upload ───────────────────────────────────────────────
@app.route("/api/upload-font", methods=["POST"])
def upload_font():
    """Accept a TTF/OTF font file, save it, and install into system fonts."""
    if "file" not in request.files:
        return jsonify({"error": "No file field"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in (".ttf", ".otf", ".woff"):
        return jsonify({"error": "Unsupported format. Use TTF or OTF."}), 400

    safe_name = f.filename
    dest = FONTS_DIR / safe_name
    try:
        f.save(str(dest))
    except Exception as e:
        return jsonify({"error": f"Save failed: {e}"}), 500

    # Install into user font directory so FFmpeg's fontconfig can resolve it
    user_fonts = Path.home() / ".fonts"
    user_fonts.mkdir(exist_ok=True)
    try:
        shutil.copy2(str(dest), str(user_fonts / safe_name))
        subprocess.run(["fc-cache", "-fv"], capture_output=True, timeout=15)
        print(f"[OK] Font installed: {safe_name}", flush=True)
    except Exception as e:
        print(f"[!] Font install warning: {e}", flush=True)

    font_name = Path(safe_name).stem
    return jsonify({"ok": True, "fontName": font_name, "filename": safe_name})


# ── Feature: Alpha Channel Export ────────────────────────────────────────────
@app.route("/api/alpha-export/<filename>")
def alpha_export(filename):
    """
    Render caption overlay as a transparent WebM (VP9 + alpha channel).
    Drop into any NLE (Premiere Pro, DaVinci Resolve, etc.) as an overlay track.
    """
    mp4_name  = Path(filename).with_suffix(".mp4").name
    clip_path = CLIPS_DIR / mp4_name
    ass_path  = CLIPS_DIR / (Path(mp4_name).stem + ".ass")
    webm_name = Path(mp4_name).stem + "_alpha.webm"
    webm_path = CLIPS_DIR / webm_name

    if not clip_path.exists():
        return jsonify({"error": "Clip not found"}), 404
    if not ass_path.exists():
        return jsonify({"error": "Caption file not available — captions must be enabled to use alpha export."}), 404

    # Get clip duration
    try:
        r_probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(clip_path)],
            capture_output=True, timeout=10
        )
        dur = float(json.loads(r_probe.stdout)["format"]["duration"])
    except Exception:
        dur = 60.0

    escaped_ass = str(ass_path.absolute()).replace("\\", "/").replace(":", "\\:")

    print(f"[*] Rendering alpha channel WebM for {mp4_name}...", flush=True)
    r = subprocess.run([
        "ffmpeg",
        "-f", "lavfi", "-i", f"color=s=1080x1920:r=30:c=black@0.0",
        "-t", str(dur),
        "-vf", f"ass='{escaped_ass}'",
        "-c:v", "libvpx-vp9",
        "-b:v", "0", "-crf", "20",
        "-pix_fmt", "yuva420p",
        "-auto-alt-ref", "0",
        "-an", "-y", str(webm_path)
    ], capture_output=True, timeout=180)

    if r.returncode != 0:
        err = r.stderr.decode(errors="replace")[-500:]
        print(f"[!] Alpha render failed: {err}", flush=True)
        return jsonify({"error": "Alpha render failed: " + err}), 500

    print(f"[OK] Alpha WebM ready: {webm_name}", flush=True)
    return send_from_directory(
        str(CLIPS_DIR), webm_name,
        mimetype="video/webm",
        as_attachment=True,
        download_name=Path(mp4_name).stem + "_alpha_captions.webm",
    )


# ── Feature: Translate SRT (Desi → English) ──────────────────────────────────
@app.route("/api/translate-srt/<filename>")
def translate_srt(filename):
    """Translate the clip's word-level transcript to English and return as SRT."""
    mp4_name = Path(filename).with_suffix(".mp4").name
    words = _load_words(mp4_name)
    if not words:
        return jsonify({"error": "Transcript not available — captions must be enabled."}), 404

    def srt_t(s: float) -> str:
        h = int(s // 3600); m = int((s % 3600) // 60)
        sec = int(s % 60);  ms = int(round((s - int(s)) * 1000))
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

    try:
        from deep_translator import GoogleTranslator
        target_lang = request.args.get("lang", "en").strip().lower()
        translator = GoogleTranslator(source="auto", target=target_lang)

        chunk_size = 6
        srt_parts  = []
        idx = 1
        for i in range(0, len(words), chunk_size):
            chunk = words[i:i + chunk_size]
            t0 = chunk[0].get("start", 0)
            t1 = chunk[-1].get("end", t0 + 2)
            text = " ".join(w.get("word", "").strip() for w in chunk if w.get("word", "").strip())
            if not text:
                continue
            try:
                translated = translator.translate(text) or text
            except Exception:
                translated = text
            srt_parts.append(f"{idx}\n{srt_t(t0)} --> {srt_t(t1)}\n{translated}\n")
            idx += 1

        srt_content = "\n".join(srt_parts)
        stem = Path(filename).stem
        return Response(
            srt_content,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}_english.srt"'},
        )
    except ImportError:
        return jsonify({"error": "Translation library not available. Run: pip install deep-translator"}), 500
    except Exception as e:
        return jsonify({"error": f"Translation failed: {e}"}), 500


# ── Feature: Raw Audio (before-enhancement preview) ──────────────────────────
@app.route("/api/audio-raw/<filename>")
def audio_raw(filename):
    """Return the raw (pre-enhancement) audio for a clip."""
    raw_name = Path(filename).stem + "_raw.mp3"
    raw_path  = CLIPS_DIR / raw_name
    if not raw_path.exists():
        return jsonify({"error": "Raw audio not available — enable Audio Enhancement when generating the clip."}), 404
    return send_from_directory(str(CLIPS_DIR), raw_name, mimetype="audio/mpeg")


@app.route("/api/upload-cookies", methods=["POST"])
def upload_cookies():
    """Accept a cookies.txt upload from the UI (multipart or JSON)."""
    content = ""
    # Prefer multipart file upload (FormData)
    if "cookies" in request.files:
        f = request.files["cookies"]
        content = f.read().decode("utf-8", errors="replace").strip()
    else:
        # Fallback: JSON body with { "content": "..." }
        data = request.get_json(force=True, silent=True) or {}
        content = data.get("content", "").strip()

    if not content:
        return jsonify({"error": "No cookie content provided"}), 400
    if "youtube.com" not in content and "google.com" not in content:
        return jsonify({"error": "File does not look like YouTube cookies — make sure you exported from youtube.com"}), 400
    try:
        COOKIES_FILE.write_text(content, encoding="utf-8")
        _cookie_ready.set()
        print(f"[Cookie] Uploaded cookies.txt ({len(content)} chars)", flush=True)
        return jsonify({"ok": True, "message": "Cookies saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cookie-status")
def cookie_status():
    has_cookies = COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 200
    return jsonify({"hasCookies": has_cookies, "ready": _cookie_ready.is_set()})


# ── Feature: Burn Hook text onto clip ────────────────────────────────────────
@app.route("/api/burn-hook/<filename>")
def burn_hook(filename):
    """Burn an AI-hook text line onto the top of the clip and return the new file."""
    mp4_name  = Path(filename).with_suffix(".mp4").name
    clip_path = CLIPS_DIR / mp4_name
    if not clip_path.exists():
        return jsonify({"error": "Clip not found"}), 404

    hook_text = request.args.get("text", "").strip()
    if not hook_text:
        return jsonify({"error": "No hook text provided"}), 400

    out_name = Path(mp4_name).stem + "_hooked.mp4"
    out_path = CLIPS_DIR / out_name

    # Escape special chars for ffmpeg drawtext
    safe = (hook_text
            .replace("\\", "\\\\")
            .replace("'",  "\\'")
            .replace(":",  "\\:")
            .replace("%",  "\\%"))

    vf = (
        f"drawtext=text='{safe}'"
        f":fontcolor=white:fontsize=52:font=Impact:bold=1"
        f":box=1:boxcolor=black@0.72:boxborderw=18"
        f":x=(w-text_w)/2:y=h*0.055"
    )

    r = subprocess.run(
        ["ffmpeg", "-i", str(clip_path), "-vf", vf,
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
         "-c:a", "copy", "-movflags", "+faststart", "-y", str(out_path)],
        capture_output=True, timeout=120,
    )
    if r.returncode != 0:
        err = r.stderr.decode(errors="replace")[-500:]
        print(f"[!] burn-hook failed: {err}", flush=True)
        return jsonify({"error": "Render failed: " + err}), 500

    return send_from_directory(
        str(CLIPS_DIR), out_name, mimetype="video/mp4",
        as_attachment=True,
        download_name=Path(mp4_name).stem + "_hooked.mp4",
    )


# ── Feature: Auto Chapter Markers ─────────────────────────────────────────────
@app.route("/api/chapters/<filename>")
def get_chapters(filename):
    """
    Detect scene changes in the clip via ffmpeg select filter, match timestamps
    to transcript words for labels, and return a JSON chapter list.
    """
    import re as _re
    mp4_name  = Path(filename).with_suffix(".mp4").name
    clip_path = CLIPS_DIR / mp4_name
    if not clip_path.exists():
        return jsonify({"error": "Clip not found"}), 404

    try:
        r = subprocess.run(
            ["ffmpeg", "-i", str(clip_path),
             "-vf", "select=gt(scene\\,0.30),showinfo",
             "-an", "-f", "null", "-"],
            capture_output=True, timeout=60,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    stderr = r.stderr.decode(errors="replace")
    scene_times: list[float] = []
    for line in stderr.splitlines():
        m = _re.search(r"pts_time:(\d+\.?\d*)", line)
        if m:
            t = float(m.group(1))
            if t > 0.3:
                scene_times.append(round(t, 2))

    # De-duplicate scenes too close together (< 1.5 s apart)
    deduped: list[float] = []
    for t in sorted(scene_times):
        if not deduped or t - deduped[-1] >= 1.5:
            deduped.append(t)

    words = _load_words(mp4_name)

    def label_at(t: float) -> str:
        if not words:
            return f"Scene"
        nearby = [w for w in words
                  if abs(float(w.get("start", 0)) - t) <= 2.5]
        if nearby:
            return " ".join(w.get("word", "").strip().title()
                            for w in nearby[:4])
        return "Scene"

    chapters = [{"time": 0.0, "label": "Intro"}]
    for t in deduped[:12]:
        chapters.append({"time": t, "label": label_at(t)})

    return jsonify({"chapters": chapters})


@app.route("/api/smart-thumbnail/<filename>")
def smart_thumbnail_route(filename):
    """On-demand 4K thumbnail: analyse the clip, generate via Pollinations.ai,
    upscale to 1920×1080 and return the URL."""
    safe = Path(filename).name
    clip_path = CLIPS_DIR / safe
    if not clip_path.exists():
        return jsonify({"error": "Clip not found"}), 404
    try:
        thumb = generate_smart_thumbnail_4k(clip_path)
        if thumb and thumb.exists():
            return jsonify({"url": f"/clips/{thumb.name}"})
        return jsonify({"error": "Thumbnail generation failed — check server logs"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/clips/<path:filename>")
def serve_clip(filename):
    return send_from_directory(str(CLIPS_DIR), filename)


@app.route("/api/video-preview")
def video_preview():
    """
    Returns YouTube video metadata for the preview card.
    Uses youtube-transcript-api + yt-dlp --dump-json (no full download).
    """
    video_id = request.args.get("v", "").strip()
    if not video_id:
        return jsonify({"error": "video ID required"}), 400

    # Check if YouTube transcript is available (instant detection mode)
    has_transcript = False
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        YouTubeTranscriptApi.list_transcripts(video_id)
        has_transcript = True
    except Exception:
        pass

    # Fetch metadata via yt-dlp (fast, skips download)
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
                "title":    info.get("title", ""),
                "channel":  info.get("channel", ""),
                "duration": int(info.get("duration", 0)),
                "views":    info.get("view_count", 0),
                "thumbnail": info.get("thumbnail", thumbnail),
            })
    except Exception:
        pass

    return jsonify(meta)


@app.route("/health")
def health():
    missing = check_deps()
    return jsonify({
        "status":        "ok" if not missing else "degraded",
        "missing_tools": missing,
    })


@app.route("/")
def root():
    return send_from_directory(str(BASE_DIR), "index.html")

@app.route("/<path:filename>")
def serve_static(filename):
    if filename in ("app.js", "style.css"):
        return send_from_directory(str(BASE_DIR), filename)
    return jsonify({"error": "File not found"}), 404


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n[>>] Voxly - Clipper Backend")
    print(f"     http://localhost:{PORT}\n")

    missing = check_deps()
    if missing:
        print(f"[!]  Missing: {', '.join(missing)}")
        print("     Install them or clips won't generate.\n")
    else:
        print("[OK] ffmpeg, ffprobe, yt-dlp found\n")

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
