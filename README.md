# Voxly – AI Viral Shorts Studio

Generate viral YouTube Shorts automatically from any YouTube video or uploaded clip.

## Features
- 🎬 **B-Roll AI Generation** – Free AI visuals via Pollinations.ai (no key needed)
- 🎙️ **AI Audio Enhancement** – 7-stage voice clarity chain (noise removal, presence EQ, compression)
- 📝 **Auto Captions** – Whisper-powered, 7 styles (MrBeast, Karaoke, Outlined, Gradient…)
- 🎯 **Face Tracker** – Dynamic OpenCV face-focus crop
- ⚡ **Speed Ramp** – Cinematic speed ramping
- 🪝 **Viral Hook Generator** – AI-written opening hooks
- 🎨 **Color Grading** – Cinematic LUTs
- 📖 **Auto Chapter Markers** – Scene-change detection
- 🖼️ **Thumbnail Generator** – One-click thumbnails
- ✂️ **Clip Trimmer** – Precise cut tool
- 🌍 **Caption Translation** – Multi-language subtitles

## Stack
- **Backend**: Python 3.11 + Flask
- **Frontend**: Vanilla HTML / CSS / JS
- **AI**: OpenAI Whisper, Pollinations.ai (Flux), Groq (optional hooks)
- **Video**: ffmpeg, yt-dlp, OpenCV

## Run
```bash
pip install -r requirements.txt
python server.py
```
