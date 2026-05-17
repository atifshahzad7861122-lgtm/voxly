from config import logger


def generate_srt_content(words: list, chunk_size: int = 4) -> str:
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
        s += 1; cs = 0
        if s >= 60: s -= 60; m += 1
        if m >= 60: m -= 60; h += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def hex_to_ass(hex_col: str) -> str:
    h = hex_col.lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}"
    elif len(h) == 8:
        a, r, g, b = h[0:2], h[2:4], h[4:6], h[6:8]
        return f"&H{a}{b}{g}{r}"
    return hex_col


STYLE_CONFIGS = {
    "mrbeast": {
        "font": "Impact", "size": 110, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&H80000000", "bold": -1,
        "outline_w": 3, "shadow": 2, "marginv": 288, "chunk": 3,
        "highlight": "&H0000FFFF", "upper": True,
    },
    "hormozi": {
        "font": "Arial Black", "size": 105, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&HA0000000", "bold": -1,
        "outline_w": 2, "shadow": 1, "marginv": 240, "chunk": 2,
        "highlight": "&H0014D4FF", "upper": True,
    },
    "garyvee": {
        "font": "Arial Black", "size": 115, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&H90000000", "bold": -1,
        "outline_w": 4, "shadow": 0, "marginv": 260, "chunk": 2,
        "highlight": "&H002165FB", "upper": True,
    },
    "loganpaul": {
        "font": "Poppins", "size": 100, "primary": "&H00E2E8F0",
        "outline": "&H00000000", "back": "&H70000000", "bold": -1,
        "outline_w": 2, "shadow": 3, "marginv": 270, "chunk": 3,
        "highlight": "&H00F8BD38", "upper": True,
    },
    "minimal": {
        "font": "Inter", "size": 90, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&H55000000", "bold": 0,
        "outline_w": 0, "shadow": 2, "marginv": 260, "chunk": 4,
        "highlight": "&H00CCCCCC", "upper": False,
    },
    "tiktok": {
        "font": "Arial Black", "size": 112, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&H80000000", "bold": -1,
        "outline_w": 3, "shadow": 2, "marginv": 280, "chunk": 2,
        "highlight": "&H00FF2DD4", "upper": True,
    },
    "imangadzi": {
        "font": "Impact", "size": 108, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&H88000000", "bold": -1,
        "outline_w": 3, "shadow": 1, "marginv": 270, "chunk": 2,
        "highlight": "&H0022B4FF", "upper": True,
    },
    "devinjatho": {
        "font": "Arial Black", "size": 118, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&H75000000", "bold": -1,
        "outline_w": 4, "shadow": 0, "marginv": 265, "chunk": 2,
        "highlight": "&H0040E040", "upper": True,
    },
    "karaoke": {
        "font": "Impact", "size": 108, "primary": "&H0000FFFF",
        "secondary": "&H88AAAAAA", "outline": "&H00000000",
        "back": "&H60000000", "bold": -1, "outline_w": 3, "shadow": 1,
        "marginv": 270, "chunk": 4, "highlight": "&H0000FFFF",
        "upper": True, "_karaoke": True,
    },
    "outlined": {
        "font": "Arial Black", "size": 106, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&H00000000", "bold": -1,
        "outline_w": 8, "shadow": 0, "marginv": 272, "chunk": 3,
        "highlight": "&H0040C0FF", "upper": True,
    },
    "gradient": {
        "font": "Impact", "size": 108, "primary": "&H00FFFFFF",
        "outline": "&H00000000", "back": "&H70000000", "bold": -1,
        "outline_w": 3, "shadow": 1, "marginv": 270, "chunk": 3,
        "highlight": "&H0000FFFF", "upper": True, "_gradient": True,
    },
}
