# Voxly — Installation Guide

## Quick Start
```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install system tools
# Windows: download ffmpeg from https://ffmpeg.org and add to PATH
# Linux:   sudo apt install ffmpeg
# macOS:   brew install ffmpeg

# 3. (Optional) GPU acceleration
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 4. Start server
python server.py

# 5. Open browser
# http://localhost:5000
```

## Verify Installation
```bash
python -c "import flask, faster_whisper, cv2; print('All OK')"
ffmpeg -version
yt-dlp --version
```
