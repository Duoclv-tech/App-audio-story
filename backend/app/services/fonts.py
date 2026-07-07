"""
Font registry + auto-download for watermark text rendering.
Ported from video-pipeline's shorts_pipeline.py:FONTS.
"""
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from loguru import logger

from app import paths

FONTS: Dict[str, Dict] = {
    "DejaVu Sans (system default)": {
        "name": "DejaVu Sans",
        "filename": None,
        "url": None,
    },
    "Be Vietnam Pro (Vietnamese)": {
        "name": "Be Vietnam Pro",
        "filename": "BeVietnamPro-Black.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/bevietnampro/BeVietnamPro-Black.ttf",
    },
    "Montserrat Black": {
        "name": "Montserrat",
        "filename": "Montserrat-Black.ttf",
        "url": "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@latest/latin-900-normal.ttf",
    },
    "Oswald Bold": {
        "name": "Oswald",
        "filename": "Oswald-Bold.ttf",
        "url": "https://cdn.jsdelivr.net/fontsource/fonts/oswald@latest/latin-700-normal.ttf",
    },
    "Inter Black": {
        "name": "Inter",
        "filename": "Inter-Black.ttf",
        "url": "https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-900-normal.ttf",
    },
    "Anton (display)": {
        "name": "Anton",
        "filename": "Anton-Regular.ttf",
        "url": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    },
    "Noto Sans Black": {
        "name": "Noto Sans",
        "filename": "NotoSans-Black.ttf",
        "url": "https://cdn.jsdelivr.net/fontsource/fonts/noto-sans@latest/latin-900-normal.ttf",
    },
    "Quicksand Bold (rounded)": {
        "name": "Quicksand",
        "filename": "Quicksand-Bold.ttf",
        "url": "https://cdn.jsdelivr.net/fontsource/fonts/quicksand@latest/latin-700-normal.ttf",
    },
}

FONTS_DIR = paths.FONTS_DIR


def list_fonts() -> List[str]:
    return list(FONTS.keys())


def ensure_font(font_key: str) -> Tuple[str, str]:
    """Ensure font is local. Auto-download if missing.
    Returns (font_name, font_file_path). Path = "" for system fonts."""
    info = FONTS.get(font_key)
    if not info:
        return ("DejaVu Sans", "")
    if not info.get("url"):
        return (info["name"], "")

    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    target = FONTS_DIR / info["filename"]
    if not target.exists():
        logger.info(f"Downloading font: {font_key}")
        try:
            r = requests.get(info["url"], timeout=60)
            r.raise_for_status()
            target.write_bytes(r.content)
            logger.info(f"Saved font: {target}")
        except Exception as e:
            logger.warning(f"Font download failed: {e}, fallback to system DejaVu Sans")
            return ("DejaVu Sans", "")
    return (info["name"], str(target))


def get_font_file_path(font_key: str) -> str:
    """Return absolute path to .ttf if it exists locally, else empty string."""
    info = FONTS.get(font_key)
    if not info or not info.get("filename"):
        return ""
    target = FONTS_DIR / info["filename"]
    return str(target) if target.exists() else ""
