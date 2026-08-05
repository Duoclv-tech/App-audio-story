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
# Default AI Voice local clone-voice presets shipped read-only with the app; seeded
# into the writable CLONE_PRESETS_DIR on first run (see clone_preset_store).
DEFAULT_CLONE_PRESETS_DIR = BUNDLE_DIR / "default_clone_presets"
# Built-in sticker library shipped read-only with the app; seeded into the
# writable STICKERS_DIR on first run (see api/video.py::_seed_default_stickers).
# In dev this points at a non-existent path so seeding is a harmless no-op —
# the dev sticker files already live in STICKERS_DIR (backend/stickers).
DEFAULT_STICKERS_DIR = BUNDLE_DIR / "default_stickers"
# Reference DB shipped read-only with the app — pre-populated with the curated
# banned-words list + AI prompts (NO stories). Copied to DB_PATH on the very
# first run so a fresh install ships those without shipping any user content.
DEFAULT_SEED_DB = BUNDLE_DIR / "default_seed.db"
# Optional bundled storage tree (audio/videos/merged...) shipped only by a
# "full dev" build. Copied into STORAGE_DIR on the first run alongside the seed
# DB so the bundled stories' media resolve. Absent in a product build.
DEFAULT_STORAGE_DIR = BUNDLE_DIR / "default_storage"

# The frontend build lives next to the app when frozen, but in dev it sits at
# <repo>/frontend/dist (a sibling of backend/, i.e. BUNDLE_DIR.parent).
if is_frozen():
    FRONTEND_DIST = BUNDLE_DIR / "frontend" / "dist"
else:
    FRONTEND_DIST = BUNDLE_DIR.parent / "frontend" / "dist"


# --- Writable per-user data ------------------------------------------------
if is_frozen():
    # Per-OS user data location so a frozen build writes to the platform-native
    # spot: %LOCALAPPDATA% on Windows, ~/.local/share (XDG) on Linux,
    # ~/Library/Application Support on macOS.
    if sys.platform == "win32":
        _local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        DATA_DIR = Path(_local) / APP_NAME
    elif sys.platform == "darwin":
        DATA_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
    else:  # linux / other posix
        _xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        DATA_DIR = Path(_xdg) / APP_NAME
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

# AI Voice local TTS: models are large (several GB) so they are NOT bundled in
# the .exe — they get downloaded at install / first run into the writable data
# dir. Clone presets (reference audio + transcript) also live under DATA_DIR.
# NOTE: the on-disk folder names below changed from an earlier build, so an
# existing install re-downloads the model once into the new folder.
MODELS_DIR = DATA_DIR / "models"
AIVOICE_LOCAL_MODEL_DIR = MODELS_DIR / "aivoice-local-model"   # fine-tune VN+EN
AIVOICE_LOCAL_BASE_DIR = MODELS_DIR / "aivoice-local-base"     # base omnilingual
CLONE_PRESETS_DIR = DATA_DIR / "clone_presets"

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
        MODELS_DIR, CLONE_PRESETS_DIR,
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
        # On POSIX the bundled ffmpeg/ffprobe ship as PyInstaller ``datas`` which
        # do NOT preserve the executable bit -> restore it so subprocess can run
        # them. No-op on Windows (.exe needs no +x).
        if sys.platform != "win32":
            import stat
            for name in ("ffmpeg", "ffprobe"):
                p = FFMPEG_BIN_DIR / name
                if p.exists():
                    try:
                        p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                    except OSError:
                        pass


def hide_subprocess_windows() -> None:
    """
    On Windows, make every subprocess (ffmpeg/ffprobe) run WITHOUT popping a
    console window. In the windowed (no-console) frozen build, each of the ~28
    ffmpeg/ffprobe calls would otherwise flash a terminal — e.g. scanning a
    folder of clips runs ffprobe per file => hundreds of windows.

    Patches subprocess.Popen once so run()/check_output()/call() are all covered.
    """
    if sys.platform != "win32":
        return
    import subprocess
    if getattr(subprocess, "_no_window_patched", False):
        return
    _CREATE_NO_WINDOW = 0x08000000
    _OrigPopen = subprocess.Popen

    class _NoWindowPopen(_OrigPopen):
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = _NoWindowPopen
    subprocess._no_window_patched = True


# Create writable dirs on import so any module can rely on them existing.
ensure_data_dirs()
