# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TruyenFull Processor — LINUX (Ubuntu) build.

This is the LIGHTWEIGHT / VBEE-only variant: it ships the cloud VBEE TTS engine
only. It deliberately does NOT bundle the local OmniVoice engine (torch + CUDA),
because that stack is huge and needs an NVIDIA GPU — impractical for a general
Linux desktop build. The OmniVoice code still ships but self-disables at runtime
when torch/omnivoice/CUDA/model are absent (VBEE keeps working).

The native window uses pywebview's GTK backend (WebKit2GTK). The target machine
therefore needs the WebKit2GTK runtime; the .github workflow installs it at
build time and PyInstaller's gi hooks bundle the GObject typelibs.

Build from the repo root (Linux, venv with requirements.txt installed):
    backend/venv/bin/pyinstaller packaging/truyenfull_linux.spec --noconfirm

Produces dist/TruyenFullProcessor/TruyenFullProcessor (onedir, ELF binary).
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO = os.path.dirname(SPECPATH)
BACKEND = os.path.join(REPO, "backend")

datas = []
binaries = []
hiddenimports = ["sqlalchemy.dialects.sqlite"]

# pywebview + its GTK/WebKit bridge. On Linux pywebview drives WebKit2GTK via
# PyGObject (``gi``); pyinstaller-hooks-contrib ships gi hooks that pull in the
# GObject-Introspection typelibs + shared libs when we collect it here.
for pkg in ("webview", "gi", "bottle"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print(f"[spec] WARN collect_all({pkg}) failed: {e}")

# uvicorn loads loops/protocols/lifespan lazily.
hiddenimports += collect_submodules("uvicorn")

# App routers/services/workers referenced indirectly.
import sys as _sys
_sys.path.insert(0, BACKEND)
hiddenimports += collect_submodules("app")

# --- App resources shipped read-only inside the bundle --------------------
datas += [
    (os.path.join(REPO, "frontend", "dist"), "frontend/dist"),
]
# Linux ffmpeg/ffprobe static binaries. The workflow downloads them into
# backend/bin_linux/ before building. Shipped under "bin" so paths.FFMPEG_BIN_DIR
# (= BUNDLE_DIR/bin) finds them; setup_ffmpeg_path() restores their +x bit.
_bin_linux = os.path.join(BACKEND, "bin_linux")
for _fname in ("ffmpeg", "ffprobe"):
    _fpath = os.path.join(_bin_linux, _fname)
    if os.path.isfile(_fpath):
        datas.append((_fpath, "bin"))
    else:
        print(f"[spec] WARN missing {_fpath} — app will fall back to system ffmpeg on PATH")

# Default OmniVoice clone-voice presets (seeded into user dir on first run).
_def_presets = os.path.join(BACKEND, "default_clone_presets")
if os.path.isdir(_def_presets):
    datas.append((_def_presets, "default_clone_presets"))
# Built-in sticker library (seeded into user's stickers dir on first run).
_def_stickers = os.path.join(BACKEND, "stickers")
if os.path.isdir(_def_stickers):
    datas.append((_def_stickers, "default_stickers"))
_fonts = os.path.join(BACKEND, "assets", "fonts")
if os.path.isdir(_fonts) and os.listdir(_fonts):
    datas.append((_fonts, "assets/fonts"))
# Reference DB (curated banned words + AI prompts, NO stories).
_seed_db = os.path.join(BACKEND, "default_seed.db")
if os.path.isfile(_seed_db):
    datas.append((_seed_db, "."))

a = Analysis(
    [os.path.join(BACKEND, "desktop.py")],
    pathex=[BACKEND],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # This build has no ML/GPU stack; exclude the heavy/PyInstaller-hostile deps
    # so a stray transitive import can't drag them in.
    excludes=[
        "tkinter", "matplotlib", "pymysql", "aiomysql",
        "torch", "torchaudio", "omnivoice", "transformers", "tokenizers",
        "accelerate", "librosa", "numba", "llvmlite", "scipy", "sklearn",
        "gradio", "gradio_client", "safehttpx", "groovy",
        # Windows-only GUI bridge; not used on Linux.
        "clr_loader", "pythonnet", "clr",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TruyenFullProcessor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed app
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TruyenFullProcessor",
)
