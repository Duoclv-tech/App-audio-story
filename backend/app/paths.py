"""
Central path resolution for the app.

Distinguishes two roots so the app works both in development and when frozen
into a Windows .exe by PyInstaller:

- BUNDLE_DIR : read-only resources shipped WITH the app (frontend build,
               bundled ffmpeg, default fonts). In dev = the ``backend/`` dir;
               when frozen = the PyInstaller extraction dir (``sys._MEIPASS``).
- DATA_DIR   : writable per-user data (SQLite db, storage, cache). In dev =
               the ``backend/`` dir (keeps the old behaviour so existing files
               stay where they were); when frozen = ``%LOCALAPPDATA%\\<app>``.

Everything else is derived from these two so no other module has to guess.
"""
import os
import sys
from pathlib import Path

APP_NAME = "TruyenFullProcessor"


def is_frozen() -> bool:
    """True when running from a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


# --- Read-only bundled resources -------------------------------------------
if is_frozen():
    # PyInstaller onedir/onefile extracts bundled ``datas`` under _MEIPASS.
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    # dev: this file is backend/app/paths.py  ->  parent.parent == backend/
    BUNDLE_DIR = Path(__file__).resolve().parent.parent

BUNDLED_FONTS_DIR = BUNDLE_DIR / "assets" / "fonts"
FFMPEG_BIN_DIR = BUNDLE_DIR / "bin"

# The frontend build lives next to the app when frozen, but in dev it sits at
# <repo>/frontend/dist (a sibling of backend/, i.e. BUNDLE_DIR.parent).
if is_frozen():
    FRONTEND_DIST = BUNDLE_DIR / "frontend" / "dist"
else:
    FRONTEND_DIST = BUNDLE_DIR.parent / "frontend" / "dist"


# --- Writable per-user data ------------------------------------------------
if is_frozen():
    _local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    DATA_DIR = Path(_local) / APP_NAME
else:
    DATA_DIR = Path(__file__).resolve().parent.parent  # backend/

STORAGE_DIR = DATA_DIR / "storage"
STORIES_DIR = STORAGE_DIR / "stories"
AUDIO_DIR = STORAGE_DIR / "audio"
VIDEO_DIR = STORAGE_DIR / "videos"
MERGED_DIR = STORAGE_DIR / "merged"
EXPORTS_DIR = STORAGE_DIR / "exports"
TRIM_TEMP_DIR = STORAGE_DIR / "trim_temp"

CACHE_DIR = DATA_DIR / "cache"
MASK_DIR = CACHE_DIR / "masks"
PREVIEW_CACHE_DIR = CACHE_DIR / "previews"
SRT_CACHE_DIR = CACHE_DIR / "srt"
STICKER_UPLOAD_DIR = CACHE_DIR / "stickers_upload"

STICKERS_DIR = DATA_DIR / "stickers"
FONTS_DIR = DATA_DIR / "fonts"
LOG_DIR = DATA_DIR / "logs"

DB_PATH = DATA_DIR / "app.db"

# DejaVu Sans Bold is the always-available fallback font for watermark text.
# Prefer the bundled copy (ships with the app); fall back to the writable
# fonts dir where fonts.py downloads extra fonts.
FALLBACK_FONT = "DejaVuSans-Bold.ttf"


def default_font_path() -> Path:
    """Absolute path to the fallback watermark font.

    Prefers the bundled copy, then a downloaded one in the writable fonts dir,
    then a font that ships with Windows (so watermarking works on any machine
    without us having to redistribute a font file).
    """
    bundled = BUNDLED_FONTS_DIR / FALLBACK_FONT
    if bundled.exists():
        return bundled
    writable = FONTS_DIR / FALLBACK_FONT
    if writable.exists():
        return writable
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
        candidate = Path(windir) / "Fonts" / name
        if candidate.exists():
            return candidate
    return writable  # last resort; may not exist


def ensure_data_dirs() -> None:
    """Create all writable data directories (idempotent)."""
    for d in (
        STORAGE_DIR, STORIES_DIR, AUDIO_DIR, VIDEO_DIR, MERGED_DIR,
        EXPORTS_DIR, TRIM_TEMP_DIR, CACHE_DIR, MASK_DIR, PREVIEW_CACHE_DIR,
        SRT_CACHE_DIR, STICKER_UPLOAD_DIR, STICKERS_DIR, FONTS_DIR, LOG_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def setup_ffmpeg_path() -> None:
    """
    Prepend the bundled ffmpeg/ffprobe directory to PATH so the many literal
    ``'ffmpeg'`` / ``'ffprobe'`` subprocess calls resolve to the shipped
    binaries. No-op in dev when backend/bin/ doesn't exist -> uses system PATH.
    """
    if FFMPEG_BIN_DIR.is_dir():
        os.environ["PATH"] = str(FFMPEG_BIN_DIR) + os.pathsep + os.environ.get("PATH", "")


# Create writable dirs on import so any module can rely on them existing.
ensure_data_dirs()
