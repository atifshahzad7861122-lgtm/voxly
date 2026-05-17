import os
import time
import unicodedata
from pathlib import Path
from threading import Lock

from config import (
    WHISPER_LANG_PROMPTS, WHISPER_VRAM_REQUIREMENTS, WHISPER_MODEL_SIZE, logger,
)
from utils.db import _save_words
from pipeline.captions import generate_srt_content, format_ass_time, STYLE_CONFIGS, hex_to_ass

whisper_model = None
whisper_lock = Lock()


def get_available_vram_mb() -> int:
    try:
        import torch
        if not torch.cuda.is_available(): return 0
        device = torch.cuda.current_device()
        total = torch.cuda.get_device_properties(device).total_memory
        reserved = torch.cuda.memory_reserved(device)
        available = (total - reserved) / (1024 * 1024)
        logger.debug(f"Available VRAM: {available:.0f}MB")
        return int(available)
    except ImportError: return 0
    except Exception as e:
        logger.warning(f"VRAM check failed: {e}")
        return 0


def load_whisper_model_safe():
    global whisper_model
    from faster_whisper import WhisperModel

    required_mb = WHISPER_VRAM_REQUIREMENTS.get(WHISPER_MODEL_SIZE, 500)
    available_mb = get_available_vram_mb()

    if available_mb > 0 and available_mb >= required_mb:
        logger.info(f"GPU mode: {available_mb}MB VRAM available, {required_mb}MB required for {WHISPER_MODEL_SIZE} model")
        device = "cuda"; compute_type = "float16"
    elif available_mb > 0 and available_mb < required_mb:
        logger.warning(f"Insufficient VRAM ({available_mb}MB < {required_mb}MB required). Falling back to CPU int8 mode.")
        device = "cpu"; compute_type = "int8"
    else:
        logger.info("No GPU detected \u2014 using CPU int8 Whisper mode")
        device = "cpu"; compute_type = "int8"

    try:
        whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device=device, compute_type=compute_type,
                                      cpu_threads=max(1, os.cpu_count() // 2))
        if not hasattr(whisper_model, "device"): whisper_model.device = device
        logger.info(f"Whisper model loaded: {WHISPER_MODEL_SIZE} on {device} ({compute_type})")
    except Exception as e:
        logger.critical(f"Critical error loading Whisper model: {e}", exc_info=True)
        whisper_model = None


def transcribe_and_generate_ass(clip_path: Path, caption_style: str = "mrbeast",
                                 language: str = None, custom_cfg: dict = None):
    global whisper_model

    with whisper_lock:
        if whisper_model is None:
            load_whisper_model_safe()
            if whisper_model is None: return None, ""

        if get_available_vram_mb() < 100 and getattr(whisper_model, "device", "cpu") == "cuda":
            logger.warning("Low VRAM detected before transcription \u2014 clearing GPU cache")
            try:
                import torch
                torch.cuda.empty_cache()
            except ImportError: pass

    lang_code = language or "en"
    logger.info(f"Starting Whisper transcription for {clip_path.name}...")
    t0 = time.time()

    segments_gen, info = whisper_model.transcribe(
        str(clip_path), language=lang_code, word_timestamps=True,
        beam_size=1, best_of=1, temperature=0.0,
        condition_on_previous_text=True,
        initial_prompt=WHISPER_LANG_PROMPTS.get(lang_code, ""),
        vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
    )

    all_segments = list(segments_gen)
    if not all_segments:
        logger.warning(f"Whisper returned no segments for {clip_path.name}")
        return None, ""

    logger.info(f"Transcription done in {time.time() - t0:.1f}s ({len(all_segments)} segments)")

    all_words = []
    for seg in all_segments:
        for w in (seg.words or []):
            all_words.append({
                "word": unicodedata.normalize("NFC", w.word.strip()),
                "start": w.start, "end": w.end,
            })
    _save_words(clip_path.name, all_words)

    srt_content = generate_srt_content(all_words)
    srt_path = clip_path.with_suffix(".srt")
    try: srt_path.write_text(srt_content, encoding="utf-8")
    except: pass

    ass_path = clip_path.with_suffix(".ass")
    cfg = dict(STYLE_CONFIGS.get(caption_style, STYLE_CONFIGS["mrbeast"]))

    if custom_cfg:
        if custom_cfg.get("font"):            cfg["font"]      = custom_cfg["font"]
        if custom_cfg.get("size"):            cfg["size"]      = int(custom_cfg["size"])
        if custom_cfg.get("primaryColor"):    cfg["primary"]   = hex_to_ass(custom_cfg["primaryColor"])
        if custom_cfg.get("outlineColor"):    cfg["outline"]   = hex_to_ass(custom_cfg["outlineColor"])
        if custom_cfg.get("highlightColor"):  cfg["highlight"] = hex_to_ass(custom_cfg["highlightColor"])
        if custom_cfg.get("outlineWidth"):    cfg["outline_w"] = int(custom_cfg["outlineWidth"])
        if custom_cfg.get("shadow") is not None:   cfg["shadow"] = int(custom_cfg["shadow"])
        if custom_cfg.get("uppercase") is not None: cfg["upper"] = bool(custom_cfg["uppercase"])
        if custom_cfg.get("wordsPerLine"):    cfg["chunk"]     = int(custom_cfg["wordsPerLine"])
        if custom_cfg.get("position") == "top":    cfg["marginv"] = 80
        elif custom_cfg.get("position") == "center": cfg["marginv"] = 900

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
    HIGHLIGHT = str(cfg["highlight"])
    HL_TAG = "{\\c" + HIGHLIGHT + "&}"
    is_karaoke = bool(cfg.get("_karaoke"))
    is_gradient = bool(cfg.get("_gradient"))

    GRAD_PALETTE = [
        "&H0069B4FF", "&H00D474C8", "&H00C4CD4E",
        "&H0038D4F7", "&H00E87840",
    ]

    chunk_size = int(cfg["chunk"])
    upper = bool(cfg["upper"])

    for segment in all_segments:
        words = segment.words or []
        for i in range(0, len(words), chunk_size):
            chunk = words[i:i + chunk_size]
            if not chunk: continue

            if is_karaoke:
                chunk_start = format_ass_time(chunk[0].start)
                chunk_end = format_ass_time(chunk[-1].end)
                parts = []
                for j, w in enumerate(chunk):
                    txt = unicodedata.normalize("NFC", w.word.strip())
                    if upper: txt = txt.upper()
                    if j < len(chunk) - 1:
                        dur_cs = max(1, int((chunk[j + 1].start - w.start) * 100))
                    else:
                        dur_cs = max(1, int((w.end - w.start) * 100))
                    parts.append(f"{{\\kf{dur_cs}}}{txt}")
                events.append(f"Dialogue: 0,{chunk_start},{chunk_end},Default,,0,0,0,,{' '.join(parts)}\\N")
            else:
                if not chunk: continue
                if all(w.start == 0 and w.end == 0 for w in chunk):
                    start_t = format_ass_time(segment.start)
                    end_t = format_ass_time(segment.end)
                    text_parts = [unicodedata.normalize("NFC", cw.word.strip()).upper() if upper else unicodedata.normalize("NFC", cw.word.strip()) for cw in chunk]
                    events.append(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{' '.join(text_parts)}\\N")
                    continue

                for word_idx, w in enumerate(chunk):
                    start_t = format_ass_time(w.start)
                    if word_idx < len(chunk) - 1:
                        end_t = format_ass_time(chunk[word_idx + 1].start)
                    else:
                        end_t = format_ass_time(w.end)

                    line_parts = []
                    for j, cw in enumerate(chunk):
                        cw_text = unicodedata.normalize("NFC", cw.word.strip())
                        if upper: cw_text = cw_text.upper()
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

    transcript_text = " ".join([s.text.strip() for s in all_segments]).strip()
    return ass_path, transcript_text
