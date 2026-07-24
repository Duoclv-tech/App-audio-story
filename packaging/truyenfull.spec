# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TruyenFull Processor (Windows desktop app) — FULL build.

Bundles the local OmniVoice TTS engine (torch + CUDA + transformers) alongside
the cloud VBEE engine, so the shipped app supports BOTH. Large (~6-10 GB onedir).
OmniVoice runs on GPU when an NVIDIA card is present, and automatically falls
back to CPU (slower) on GPU-less machines — see app/services/omnivoice_processor.

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

# --- ML stack for OmniVoice ------------------------------------------------
# torch/omnivoice are imported lazily in app.services.omnivoice_processor, so
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
# Default OmniVoice clone-voice presets (seeded into user dir on first run).
_def_presets = os.path.join(BACKEND, "default_clone_presets")
if os.path.isdir(_def_presets):
    datas.append((_def_presets, "default_clone_presets"))
_fonts = os.path.join(BACKEND, "assets", "fonts")
if os.path.isdir(_fonts) and os.listdir(_fonts):
    datas.append((_fonts, "assets/fonts"))

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
