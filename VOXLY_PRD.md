# Voxly — Product Requirements Document

> **Version:** 1.0.0  
> **Date:** 2026-05-17  
> **Stack:** Python (Flask) backend + Vanilla JS frontend (Vite dev server)

---

## 1. Product Overview

Voxly transforms long-form YouTube videos into viral-ready 9:16 Shorts/TikTok clips. Given a URL or uploaded video, it:

1. **Downloads** the source video (yt-dlp with auto cookie extraction)
2. **Detects** the most speech-dense/high-energy segments
3. **Transcribes** speech via Whisper (or uses YouTube transcripts when available)
4. **Renders** 9:16 clips with animated captions in 11 styles, optional face-tracking crop, color grades, auto-zoom, emoji bursts, logo watermarks, and B-roll overlays
5. **Generates** AI thumbnails, viral hook text, and SRT subtitle files
6. **Exports** in MP4 (H.264), WebM (VP9), or MOV (PNG alpha) formats at 480p–4K

---

## 2. Architecture

### 2.1 System Diagram

```
┌──────────────┐     Vite Dev Server     ┌──────────────────┐
│   Browser    │◄──── port 5173 ────────►│   app.js         │
│  (index.html)│     proxy /api → :5000  │   index.html     │
└──────────────┘                          │   style.css      │
                                          └────────┬─────────┘
                                                   │ HTTP /api/*
                                                   ▼
┌──────────────────────────────────────────────────────────────┐
│  Flask Backend ──── port 5000                                │
│                                                              │
│  server.py (39 lines)                                        │
│    ├── routes/process.py    ◄── POST /api/process (SSE)      │
│    ├── routes/media.py      ◄── file uploads, export         │
│    ├── routes/history.py    ◄── SQLite CRUD                  │
│    └── routes/tools.py      ◄── health, cookies, meta        │
│                                                              │
│    ┌────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐   │
│    │pipeline│  │  vision/  │  │ thumbnail/│  │  utils/  │   │
│    │  9 files│  │ face_track│  │ generator │  │ db,fonts,│   │
│    │        │  │           │  │           │  │ ffmpeg   │   │
│    └────────┘  └───────────┘  └───────────┘  └──────────┘   │
│                                                              │
│  External:                                                   │
│    ├── yt-dlp          ── YouTube download                   │
│    ├── ffmpeg/ffprobe  ── video processing                   │
│    ├── faster-whisper  ── local transcription                │
│    ├── Groq API        ── viral hook generation              │
│    ├── Pollinations.ai ── AI thumbnail + B-roll images       │
│    ├── YouTube Transcript API ── instant captions            │
│    └── Google Translate ── SRT translation                   │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 Directory Structure

```
voxly/
├── server.py                 # 39 lines — Flask entrypoint
├── config.py                 # 232 lines — all constants
├── requirements.txt          # Python dependencies
├── voxly_history.db          # SQLite database (auto-created)
│
├── pipeline/                 # Core processing pipeline
│   ├── download.py           # yt-dlp downloader + cookie engine
│   ├── segments.py           # Speech/energy segment detection
│   ├── transcribe.py         # Whisper transcription + ASS generation
│   ├── captions.py           # SRT/ASS formatters + 11 style configs
│   ├── filters.py            # FFmpeg filter chain builder
│   ├── encode.py             # Clip cutting (single-pass + 2-pass)
│   ├── effects.py            # Emoji, auto-zoom, speed ramp, logo
│   ├── hooks.py              # Groq LLM hooks + viral score
│   └── broll.py              # B-roll image download + composite
│
├── routes/                   # Flask Blueprints
│   ├── process.py            # POST /api/process (main pipeline)
│   ├── media.py              # Upload, trim, export, rebake
│   ├── history.py            # History/stats CRUD
│   └── tools.py              # Health, cookies, chapters, meta
│
├── vision/                   # Computer vision
│   └── face_track.py         # Haar cascade face detection + ffmpeg expr
│
├── thumbnail/                # Thumbnail generation
│   └── generator.py          # AI + frame + gradient thumbnail pipeline
│
├── utils/                    # Shared utilities
│   ├── ffmpeg.py             # ffprobe wrappers, audio energy
│   ├── fonts.py              # Font resolution + path escaping
│   └── db.py                 # SQLite init + word cache
│
├── assets/                   # Static assets
│   └── fonts/                # Bundled fonts (DejaVuSans-Bold.ttf)
│
├── frontend/                 # Frontend (Vanilla JS)
│   ├── index.html            # SPA shell (1081 lines)
│   ├── app.js                # All UI logic (1990 lines)
│   └── style.css             # All styling
│
├── package.json              # Node dependencies (Vite, React, Tailwind)
├── vite.config.ts            # Dev server config
└── tsconfig.json             # TypeScript config (unused)
```

**24 Python source files, ~3,127 lines total** (down from a 3,909-line monolith).

---

## 3. Feature Inventory — Working Status

### 3.1 ✅ WORKING — Fully Functional

| Feature | Description | Verified |
|---------|-------------|----------|
| **YouTube Download** | yt-dlp with format selection, cookie auto-extraction from Chrome/Edge/Brave/Opera/Vivaldi/Firefox, background refresh loop | ✅ |
| **Auto Cookie Engine** | Extracts YouTube cookies from browser SQLite DBs even while browser is open. Falls back to manual cookies.txt upload | ✅ |
| **Quality Floor** | Prevents outputting lower resolution than source (e.g. 1080p source → minimum 720p output) | ✅ |
| **Segment Detection** | YouTube Transcript API (instant) → Audio RMS energy (fallback). Greedy peak selection with minimum gap enforcement | ✅ |
| **Whisper Transcription** | GPU/CPU auto-detect, VRAM safety check, VAD filtering, NFC normalization | ✅ |
| **11 Caption Styles** | mrbeast, hormozi, garyvee, loganpaul, minimal, tiktok, imangadzi, devinjatho, karaoke, outlined, gradient | ✅ |
| **Custom Caption Style** | Font, size, color, outline, shadow, position, uppercase per-clip override from frontend | ✅ |
| **9:16 Crop (Fill/Pad)** | Center crop or letterbox pad to 1080×1920 | ✅ |
| **Face Tracking Crop** | OpenCV Haar cascade, trajectory smoothing, ffmpeg piecewise-linear crop expression | ✅ |
| **6 Color Grades** | none, warm, cool, vintage, cinematic, vibrant | ✅ |
| **Auto Zoom** | Audio-energy-triggered 22% punch-in crop at peak moments | ✅ |
| **Emoji Burst** | Keyword-triggered drawtext overlays (16 keywords mapped) | ✅ |
| **Logo Watermark** | Position (4 corners), size (small/medium/large), opacity | ✅ |
| **Speed Ramp** | Variable playback speed (1.35× low-energy, 1× high-energy) | ✅ |
| **Audio Enhancement** | High-pass filter, noise reduction, EQ, compression, loudness normalization | ✅ |
| **Two-Pass Encoding** | For 1080p output — ~2× slower, noticeably better quality | ✅ |
| **4 Export Formats** | MP4 (H.264+AAC), WebM (VP9+Opus), MOV (PNG alpha), MOV (ProRes) | ✅ |
| **4 Resolutions** | 480p, 720p, 1080p, 4K | ✅ |
| **SRT Generation** | Word-level SRT with configurable chunk size | ✅ |
| **Viral Hooks (Groq)** | LLM-generated hook text from transcript (3 per clip) | ✅ |
| **Viral Score** | 1–10 heuristic scoring based on duration, WPM, hook keywords, style, B-roll count | ✅ |
| **B-Roll AI Overlay** | Pollinations.ai image generation, image→video, overlay at speech gaps | ✅ |
| **Thumbnail (3-tier)** | 1) Pollinations.ai AI image → 2) Best-scored video frame → 3) Gradient fallback, with text overlay | ✅ |
| **Clip Trimmer** | Re-encode clip to [start, end] window, stream as download | ✅ |
| **Alpha Channel Export** | Transparent WebM with captions only (for NLE overlay) | ✅ |
| **Burn Hook Text** | Permanently burn AI-generated hook onto top of clip | ✅ |
| **Auto Chapters** | ffmpeg scene detection + transcript word labeling | ✅ |
| **YouTube Preview** | Title, channel, duration, views, transcript availability via yt-dlp --dump-json | ✅ |
| **History (SQLite)** | Paginated clip history, stats dashboard, delete individual/clear all | ✅ |
| **Font Upload** | TTF/OTF upload, copies to `~/.fonts`, runs `fc-cache` on Linux | ✅ |
| **SRT Translation** | Google Translate via deep-translator | ✅ |
| **Health Check** | Dependency verification, VRAM status, yt-dlp version | ✅ |
| **yt-dlp Auto-Update** | Background update on startup + manual trigger + 7-day interval check | ✅ |

### 3.2 ⚠️ PARTIAL — Working but with Caveats

| Feature | Issue |
|---------|-------|
| **Whisper on CPU** | Falls back to CPU int8 when no GPU — functional but ~10× slower than GPU. No progress reporting during transcription |
| **YouTube Transcript API** | Only works for videos that have auto-captions enabled. Falls back to Whisper which requires download first |
| **Groq API Key Validation** | Pre-flight check sends a "ping" request — consumes 1 token per attempt. Valid format keys pass even if rate-limited |
| **Rebake Captions** | Duplicates `STYLE_CONFIGS` — changes to styles in `captions.py` won't affect rebake. Must be updated manually in both places |
| **Cookie Engine** | Direct SQLite read on Windows works for Chromium browsers. Firefox extraction only works via yt-dlp native (browser must be closed) |

### 3.3 ❌ NOT WORKING / DISABLED

| Feature | Issue |
|---------|-------|
| **React Frontend** | `src/App.tsx` (42 lines) is a dead placeholder — never loaded. The real UI is `index.html` + `app.js` (vanilla JS). The Vite config has React plugin but it's unused |
| **Standalone Effects** | `apply_auto_zoom()`, `apply_speed_ramp()`, `apply_logo_overlay()` in `pipeline/effects.py` are **dead code** — they duplicate the inlined logic in `pipeline/filters.py` and are never called anywhere |
| **detect_content_center()** | Legacy function in `pipeline/filters.py` — defined but never called. Superseded by face tracking |
| **FONT_CANDIDATES dict** | In `utils/fonts.py` — defined but never used. The `resolve_font_path()` function has its own hardcoded search paths |
| **4K Output** | Technically works but logs a warning "this will be slow on CPU". No GPU acceleration for encoding. On most systems, 4K rendering will timeout at 5 minutes |
| **TypeScript Support** | `tsconfig.json` exists, `src/` has `.tsx` files, but none are included in the build pipeline. Vite only serves `index.html` directly |
| **Tailwind CSS** | Listed in `package.json` but not used in the vanilla JS frontend. Tailwind classes are never present in `index.html` or `app.js` |

---

## 4. API Reference — 25 Endpoints

### 4.1 Core Pipeline

```http
POST /api/process
Content-Type: application/json

{
  "youtubeUrl": "https://youtube.com/watch?v=...",
  "groqKey": "gsk_...",
  "sourceType": "youtube" | "upload",
  "uploadFile": "filename.mp4",
  "clips": 5,
  "duration": 60,
  "captions": true,
  "captionStyle": "mrbeast",
  "mode": "fill" | "pad",
  "language": "english",
  "audioEnhance": false,
  "colorGrade": "none",
  "autoZoom": false,
  "emojiBurst": false,
  "faceFocus": false,
  "speedRamp": false,
  "brollEnabled": false,
  "customStyle": { "font": "...", "primaryColor": "#FFFFFF", ... },
  "logoConfig": { "filename": "logo.png", "corner": "br", "opacity": 0.8, "size": "medium" },
  "resolution": "1080p",
  "export_format": "mp4"
}

Response: SSE stream (application/x-ndjson)
  {"total": 5}
  {"type": "clip_ready", "clip": "/clips/short_1_abc123.mp4", "index": 0, ...}
  {"type": "clip_ready", "clip": "/clips/short_2_def456.mp4", "index": 1, ...}
  {"thumbReady": true, "index": 0}
  {"thumbReady": true, "index": 1}
```

### 4.2 File Management

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/upload-video` | Upload source video (returns filename, duration, dimensions) |
| POST | `/api/upload-logo` | Upload logo image (returns filename) |
| POST | `/api/upload-font` | Upload TTF/OTF font (installs to system) |
| POST | `/api/cookies` | Upload cookies.txt content |
| GET | `/api/cookie-status` | Check if cookies are available |

### 4.3 Clip Export & Editing

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/clips/<filename>` | Serve clip file |
| GET | `/api/clip-srt/<filename>` | Download SRT file |
| GET | `/api/clip-transcript/<filename>` | Get word-level JSON transcript |
| POST | `/api/rebake-captions` | Re-render clip with edited captions |
| GET | `/api/trim-clip/<filename>?start=&end=` | Trim and stream clip |
| GET | `/api/alpha-export/<filename>` | Transparent WebM with captions only |
| GET | `/api/burn-hook/<filename>?text=` | Burn hook text onto clip |
| GET | `/api/audio-raw/<filename>` | Raw pre-enhancement audio |
| GET | `/api/translate-srt/<filename>?lang=` | Translated SRT |

### 4.4 Metadata & Tools

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/video-preview?v=` | YouTube video metadata |
| GET | `/api/chapters/<filename>` | Scene-detect chapters with labels |
| GET | `/health` | Server health + deps + VRAM |
| POST | `/api/update-ytdlp` | Trigger yt-dlp update |

### 4.5 History

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/history?page=&limit=` | Paginated clip history |
| GET | `/api/stats` | Dashboard aggregate stats |
| DELETE | `/api/history/<id>` | Delete single record |
| DELETE | `/api/history` | Clear all history |

---

## 5. Data Flow — Full Request Lifecycle

```
User clicks "Generate" in UI
  │
  ▼
app.js: POST /api/process { youtubeUrl, groqKey, captionStyle, ... }
  │
  ▼
routes/process.py: process()
  ├── 1. Validate Groq API key (ping endpoint)
  ├── 2. Parse all params (resolution, format, style, etc.)
  ├── 3. Start NDJSON stream
  │
  ▼
generate() generator
  ├── 4. DOWNLOAD
  │     ├── download_video(url) → yt-dlp with cookies
  │     └── verify_download_quality() → enforce_quality_floor()
  │
  ├── 5. ANALYZE
  │     ├── get_video_info() → duration, width, height
  │     └── find_speech_dense_segments()
  │           ├── Try YouTube Transcript API (instant)
  │           └── Fallback: extract_audio_energy() → RMS peaks
  │
  ├── 6. LOG SESSION → SQLite
  │
  ├── 7. RENDER CLIPS (ThreadPool × 2)
  │     └── cut_clip() per segment:
  │           ├── Extract raw audio MP3 (ffmpeg)
  │           ├── Transcribe (Whisper) → .ass captions + .srt + words.json
  │           ├── build_unified_vf_chain():
  │           │     ├── Crop to 9:16 (fill/pad/face-track)
  │           │     ├── Color grade
  │           │     ├── Auto-zoom (if enabled)
  │           │     ├── Emoji burst (if enabled)
  │           │     ├── ASS subtitle overlay
  │           │     ├── Logo watermark (if configured)
  │           │     ├── Audio enhancement (if enabled)
  │           │     └── Speed ramp (if enabled)
  │           └── Encode (single-pass or 2-pass)
  │
  ├── 8. POST-PROCESS (per clip)
  │     ├── generate_viral_hooks() → Groq LLM → 3 hook texts
  │     ├── B-roll: extract moments → download images → compose (if enabled)
  │     ├── calculate_viral_score()
  │     ├── YIELD {"type":"clip_ready", ...}
  │     └── INSERT INTO clips (SQLite)
  │
  └── 9. THUMBNAILS (ThreadPool × 3)
        └── generate_thumbnail():
              ├── build_thumbnail_prompt() → hook + transcript
              ├── Try: Pollinations.ai API
              ├── Fallback: extract_best_thumbnail_frame() → ffmpeg signalstats
              └── Fallback: generate_gradient_thumbnail() → ffmpeg gradients
              └── Composite text overlay → ffmpeg drawtext
              └── YIELD {"thumbReady": true, ...}
```

---

## 6. Configuration Reference

### 6.1 Paths (config.py)

| Variable | Default | Purpose |
|----------|---------|---------|
| `BASE_DIR` | `Path(__file__).parent` | Project root |
| `CLIPS_DIR` | `BASE_DIR / "clips"` | Generated clip output |
| `DOWNLOADS_DIR` | `BASE_DIR / "downloads"` | YouTube download cache |
| `UPLOADS_DIR` | `BASE_DIR / "uploads"` | Uploaded video files |
| `FONTS_DIR` | `BASE_DIR / "fonts"` | User-uploaded fonts |
| `LOGOS_DIR` | `BASE_DIR / "logos"` | User-uploaded logos |
| `DB_PATH` | `BASE_DIR / "voxly_history.db"` | SQLite database |
| `COOKIES_FILE` | `BASE_DIR / "cookies.txt"` | YouTube cookies (Netscape format) |
| `BUNDLED_FONT_DIR` | `BASE_DIR / "assets" / "fonts"` | Built-in fonts |

### 6.2 Processing Defaults

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | Flask port |
| `MAX_CLIPS` | `5` | Maximum clips per video |
| `DEFAULT_DURATION` | `60` | Target clip length (seconds) |
| `MIN_GAP_SECONDS` | `30` | Minimum gap between clip starts |
| `SAMPLE_RATE` | `44100` | Audio analysis sample rate |
| `ENERGY_WINDOW` | `0.5` | RMS energy window (seconds) |

### 6.3 Caption Styles (11)

| Style | Font | Size | Outline | Shadow | Chunk | Uppercase | Highlight Color |
|-------|------|------|---------|--------|-------|-----------|-----------------|
| mrbeast | Impact | 110 | 3 | 2 | 3 | Yes | Yellow |
| hormozi | Arial Black | 105 | 2 | 1 | 2 | Yes | Amber-Yellow |
| garyvee | Arial Black | 115 | 4 | 0 | 2 | Yes | Orange |
| loganpaul | Poppins | 100 | 2 | 3 | 3 | Yes | Cyan |
| minimal | Inter | 90 | 0 | 2 | 4 | No | Soft Grey |
| tiktok | Arial Black | 112 | 3 | 2 | 2 | Yes | Hot Pink |
| imangadzi | Impact | 108 | 3 | 1 | 2 | Yes | Gold |
| devinjatho | Arial Black | 118 | 4 | 0 | 2 | Yes | Neon Green |
| karaoke | Impact | 108 | 3 | 1 | 4 | Yes | Yellow (sweep) |
| outlined | Arial Black | 106 | 8 | 0 | 3 | Yes | Amber |
| gradient | Impact | 108 | 3 | 1 | 3 | Yes | 5-color palette |

### 6.4 Resolutions

| Key | Width | Height | Bitrate | CRF | Preset |
|-----|-------|--------|---------|-----|--------|
| 480p | 480 | 854 | 1500k | 23 | ultrafast |
| 720p | 720 | 1280 | 4000k | 20 | veryfast |
| 1080p | 1080 | 1920 | 8000k | 18 | slow |
| 4k | 2160 | 3840 | 20000k | 16 | medium |

### 6.5 Export Formats

| Format | Extension | Video Codec | Audio Codec | Pixel Format |
|--------|-----------|-------------|-------------|--------------|
| MP4 | .mp4 | libx264 | aac | yuv420p |
| WebM | .webm | libvpx-vp9 | libopus | yuv420p |
| MOV Alpha | .mov | png | aac | rgba |
| MOV ProRes | .mov | prores | aac | yuv422p10le |

---

## 7. External Dependencies

### 7.1 System Dependencies
- **ffmpeg + ffprobe** (must be in PATH) — all video processing
- **yt-dlp** — YouTube downloading + cookie extraction
- **Python ≥3.8** — backend

### 7.2 Python Packages (requirements.txt)
| Package | Purpose |
|---------|---------|
| flask | Web framework |
| flask-cors | Cross-origin requests |
| requests | HTTP client (Pollinations, etc.) |
| faster-whisper | Local speech transcription (GPU/CPU) |
| youtube-transcript-api | YouTube instant captions |
| deep-translator | SRT translation |
| opencv-python | Face detection (Haar cascade) |
| numpy | Array operations (face tracking) |
| yt-dlp | Video downloader |

### 7.3 External APIs
| Service | Purpose | Auth | Rate Limit |
|---------|---------|------|------------|
| Groq API | Viral hook generation (LLaMA 3.3 70B) | API key (free) | 30 req/min (free tier) |
| Pollinations.ai | AI thumbnails + B-roll images | None (free) | ~30 req/min (unofficial) |
| YouTube Transcript API | Instant captions | None (free) | ~100 req/min |
| Google Translate (deep-translator) | SRT translation | None (free) | ~50 req/min |

---

## 8. Configuration & Setup

### 8.1 Quick Start
```bash
pip install -r requirements.txt
python server.py
# → http://localhost:5000
```

### 8.2 Frontend Dev Server
```bash
npm install
npm run dev
# → http://localhost:5173 (proxies /api → :5000)
```

### 8.3 Groq API Key (Required)
1. Get free key at https://console.groq.com
2. Pass in each request via `groqKey` field OR set `GROQ_API_KEY` env var

### 8.4 YouTube Cookies (Auto)
The cookie engine automatically extracts YouTube login cookies from Chrome/Edge/Brave on startup.  
If auto-extraction fails, manually export cookies via "Get cookies.txt" Chrome extension and upload via the UI.

---

## 9. Known Issues & Technical Debt

### 9.1 Bugs (Non-Critical)

| ID | Severity | Description | File |
|----|----------|-------------|------|
| B1 | Low | Concurrent Whisper requests race on model loading (lock only held during `is None` check, not during `model.transcribe()`) | `pipeline/transcribe.py:64-67` |
| B2 | Low | SQLite connections in `process.py:149-155` and `process.py:248-258` are not explicitly closed after `with conn:` (auto-closed on GC, but leaks over many requests) | `routes/process.py` |
| B3 | Low | `segments[result["index"]]` in post-processing could throw `IndexError` if thread results come back out of order and index is stale | `routes/process.py:253-256` |
| B4 | Low | Many magic CRF values (20, 23, 26, 28) scattered across media routes instead of centralized in config | `routes/media.py:101,228,265,326` |

### 9.2 Code Duplication

| ID | Description | Impact |
|----|-------------|--------|
| D1 | `STYLE_CONFIGS` fully duplicated as `STYLE_CONFIGS_REBAKE` in `routes/media.py:167-179` (11 styles, identical values) | Changes to styles in captions.py won't affect rebake |
| D2 | `apply_auto_zoom()`, `apply_speed_ramp()`, `apply_logo_overlay()` in `pipeline/effects.py` duplicate the inlined logic in `pipeline/filters.py:99-111,163-204,131-143` | Dead code — never called, increases maintenance burden |

### 9.3 Performance Considerations

| Concern | Details |
|---------|---------|
| Whisper CPU mode | ~10× slower than GPU. A 60s clip takes ~60s to transcribe on CPU vs ~6s on GPU |
| 4K rendering | Will likely timeout on CPU-only systems. 5-minute timeout may not be sufficient |
| B-roll download | Pollinations.ai requests can take 30-55s each. All B-rolls for a clip download in parallel (3 workers) |
| Two-pass encoding | ~2× slower than single-pass. Only enabled for 1080p output |
| Cookie battery | Cookie refresh loop runs every 30 minutes. Each iteration tries all 7 browsers serially (~3-5s total) |

### 9.4 Frontend Limitations

| Issue | Description |
|-------|-------------|
| React code is dead | `src/App.tsx` (42 lines) is a placeholder, never loaded. Vite only serves `index.html` directly |
| SPA is in vanilla JS | 1,990-line `app.js` is a monolithic single-file SPA — no component architecture |
| No build step for frontend | Vite serves `index.html`/`app.js`/`style.css` directly from root. No bundling, no minification |
| Tailwind unused | Listed in `package.json` but no Tailwind classes are used in `index.html` or `app.js` |

---

## 10. Frontend Architecture

### 10.1 Screens
1. **Studio** — Main workspace: URL input, settings panels, clip gallery
2. **Dashboard** — Stats overview (videos, clips, viral scores, hours saved)
3. **History** — Paginated table with search, delete, re-download

### 10.2 Key UI Components (all in app.js)

| Component | Lines | Purpose |
|-----------|-------|---------|
| StreamingConsumer | ~150 | Read NDJSON stream from /api/process, parse events, update UI |
| GalleryRenderer | ~200 | Display generated clips with thumbnail, download buttons, action modals |
| SettingsPanel | ~300 | All config panels (Segment 1–5) — caption style, color grade, resolution, format, etc. |
| CaptionEditor | ~150 | Word-by-word transcript editor with timeline |
| ChapterMarkers | ~80 | Display auto-detected chapters + labels |
| DashboardCharts | ~100 | Viral score distribution, clips per day, top sources |
| ToastNotifier | ~50 | Transient success/error notifications |

### 10.3 Frontend API Calls (all from app.js)

All 25 backend endpoints have corresponding consumers in `app.js`. The frontend uses `fetch()` with manual NDJSON line parsing for the streaming `/api/process` endpoint, and standard `fetch()` JSON for all other endpoints.

---

## 11. Development Roadmap

### 11.1 Immediate Fixes (High Priority)
- [ ] Remove `STYLE_CONFIGS_REBAKE` duplication — import from `captions.py` instead
- [ ] Remove dead code (`apply_auto_zoom`, `apply_speed_ramp`, `apply_logo_overlay`, `detect_content_center`, `FONT_CANDIDATES`)
- [ ] Close SQLite connections properly in `process.py`

### 11.2 Short-Term (Medium Priority)
- [ ] Add transcription progress reporting (Whisper doesn't support this natively, but could emit periodic events)
- [ ] Centralize CRF values into config.py
- [ ] Add concurrent request lock for Whisper (prevent double model load)
- [ ] Move `_extract_video_id()` to public module

### 11.3 Long-Term (Low Priority)
- [ ] Port vanilla JS frontend to React (the `src/` directory is already scaffolded)
- [ ] Add GPU acceleration for encoding (NVIDIA NVENC / AMD AMF)
- [ ] Add background task queue (Celery / Redis) for processing
- [ ] Add user authentication and per-user clip storage
- [ ] Add webhook notification when processing completes
