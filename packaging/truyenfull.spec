# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TruyenFull Processor (Windows desktop app) — FULL build.

Bundles the local AI Voice local TTS engine (torch + CUDA + transformers)
alongside the cloud VBEE engine, so the shipped app supports BOTH. Large
(~6-10 GB onedir). AI Voice local runs on GPU when an NVIDIA card is present,
and automatically falls back to CPU (slower) on GPU-less machines — see
app/services/ai_voice_local_processor.

Build from the repo root (venv must have requirements.lock.txt installed):
    backend/venv/Scripts/pyinstaller.exe packaging/truyenfull.spec --noconfirm

Produces dist/TruyenFullProcessor/TruyenFullProcessor.exe (onedir).
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO = os.path.dirname(SPECPATH)
BACKEND = os.path.join(REPO, "backend")

datas = []
binaries = []
hiddenimports = ["sqlalchemy.dialects.sqlite"]

# pywebview + its .NET bridge (WebView2 on Windows).
for pkg in ("webview", "clr_loader", "pythonnet", "bottle"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# uvicorn loads loops/protocols/lifespan lazily.
hiddenimports += collect_submodules("uvicorn")

# --- ML stack for AI Voice local -------------------------------------------
# torch / the omnivoice pip package are imported lazily in
# app.services.ai_voice_local_processor, so
# PyInstaller's static analysis won't discover them — collect them explicitly.
# collect_all pulls each package's data files + binaries (incl. torch's bundled
# CUDA DLLs from the cu124 wheel) + submodules.
ML_PACKAGES = [
    "torch", "torchaudio", "omnivoice", "transformers", "tokenizers",
    "safetensors", "accelerate", "huggingface_hub", "soundfile", "soxr",
    "librosa", "numba", "llvmlite", "scipy", "sklearn", "truststore",
    "regex", "webdataset",
]
for pkg in ML_PACKAGES:
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print(f"[spec] WARN collect_all({pkg}) failed: {e}")

# App routers/services/workers referenced indirectly.
import sys as _sys
_sys.path.insert(0, BACKEND)
hiddenimports += collect_submodules("app")

# --- App resources shipped read-only inside the bundle --------------------
datas += [
    (os.path.join(REPO, "frontend", "dist"), "frontend/dist"),
    (os.path.join(BACKEND, "bin", "ffmpeg.exe"), "bin"),
    (os.path.join(BACKEND, "bin", "ffprobe.exe"), "bin"),
]
# Default AI Voice local clone-voice presets (seeded into user dir on first run).
_def_presets = os.path.join(BACKEND, "default_clone_presets")
if os.path.isdir(_def_presets):
    datas.append((_def_presets, "default_clone_presets"))
# Built-in sticker library (seeded into user's stickers dir on first run).
# Shipped as "default_stickers" so it maps to paths.DEFAULT_STICKERS_DIR.
_def_stickers = os.path.join(BACKEND, "stickers")
if os.path.isdir(_def_stickers):
    datas.append((_def_stickers, "default_stickers"))
_fonts = os.path.join(BACKEND, "assets", "fonts")
if os.path.isdir(_fonts) and os.listdir(_fonts):
    datas.append((_fonts, "assets/fonts"))
# Reference DB (curated banned words + AI prompts, NO stories). Shipped at the
# bundle root so paths.DEFAULT_SEED_DB finds it; copied to the user's writable
# DB on first run only. See app/seed.py::restore_seed_db_if_fresh.
_seed_db = os.path.join(BACKEND, "default_seed.db")
if os.path.isfile(_seed_db):
    datas.append((_seed_db, "."))
# Full-dev build: build.ps1 -Mode fulldev sets SEED_STORAGE_DIR to the storage
# tree to ship alongside the (full) seed DB. Unset in a product build -> no media.
_seed_storage = os.environ.get("SEED_STORAGE_DIR", "").strip()
if _seed_storage and os.path.isdir(_seed_storage):
    datas.append((_seed_storage, "default_storage"))
    print(f"[spec] full-dev: bundling storage from {_seed_storage}")

a = Analysis(
    [os.path.join(BACKEND, "desktop.py")],
    pathex=[BACKEND],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # gradio is a transitive dep of omnivoice but NOT needed for inference
    # (verified: `from omnivoice import OmniVoice` does not import gradio).
    # Excluding it avoids gradio's heavy, PyInstaller-hostile assets.
    excludes=[
        "tkinter", "matplotlib", "pymysql", "aiomysql",
        "gradio", "gradio_client", "safehttpx", "groovy",
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
    console=False,          # windowed app, no terminal
    disable_windowed_traceback=False,
    icon=os.path.join(SPECPATH, "app.ico") if os.path.exists(os.path.join(SPECPATH, "app.ico")) else None,
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
