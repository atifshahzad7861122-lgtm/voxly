import os
import platform
from pathlib import Path

from config import BUNDLED_FONT_DIR, logger


def resolve_font_path() -> str | None:
    """
    Resolve a valid bold font path for ffmpeg drawtext.
    Checks project-bundled font first, then OS system fonts.
    Returns valid path string or None if nothing found.
    """
    system = platform.system()

    candidates = [
        str(BUNDLED_FONT_DIR / "DejaVuSans-Bold.ttf"),
    ]

    if system == "Windows":
        candidates += [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/Arial_Bold.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
        ]
    elif system == "Darwin":
        candidates += [
            "/Library/Fonts/Arial Bold.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Arial.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        ]

    for path in candidates:
        if os.path.exists(path):
            logger.info(f"Thumbnail font resolved: {path}")
            return path

    logger.warning(
        "No font found for thumbnail text overlay. "
        "Thumbnails will render without text. "
        "Fix: place DejaVuSans-Bold.ttf at assets/fonts/DejaVuSans-Bold.ttf"
    )
    return None


FONT_CANDIDATES: dict[str, list[str]] = {
    "Windows": [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial_Bold.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ],
    "Darwin": [
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
    ],
    "Linux": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ],
}


def escape_font_path(path: str) -> str:
    """
    Escape font path for ffmpeg drawtext filter.
    Windows paths need backslashes converted and colons escaped.
    Linux/macOS paths with spaces need single-quote wrapping.
    """
    if platform.system() == "Windows":
        path = path.replace("\\", "/")
        path = path.replace(":", "\\\\:")
        return path
    else:
        if " " in path:
            return f"'{path}'"
        return path
