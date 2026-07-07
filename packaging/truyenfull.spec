# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TruyenFull Processor (Windows desktop app).

Build from the repo root:
    backend/venv/Scripts/pyinstaller.exe packaging/truyenfull.spec --noconfirm

Produces dist/TruyenFullProcessor/TruyenFullProcessor.exe (onedir).
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is the directory containing this .spec (i.e. <repo>/packaging),
# so the repo root is its parent.
REPO = os.path.dirname(SPECPATH)
BACKEND = os.path.join(REPO, "backend")

datas = []
binaries = []
hiddenimports = ["sqlalchemy.dialects.sqlite"]

# pywebview + its .NET bridge (WebView2 on Windows) need their data/binaries
# and submodules collected explicitly.
for pkg in ("webview", "clr_loader", "pythonnet", "bottle"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# uvicorn loads its loops/protocols/lifespan lazily -> pull them all in.
hiddenimports += collect_submodules("uvicorn")

# App routers/services/workers may be referenced indirectly -> bundle them all.
import sys as _sys
_sys.path.insert(0, BACKEND)
hiddenimports += collect_submodules("app")

# --- App resources shipped read-only inside the bundle --------------------
datas += [
    (os.path.join(REPO, "frontend", "dist"), "frontend/dist"),
    (os.path.join(BACKEND, "bin", "ffmpeg.exe"), "bin"),
    (os.path.join(BACKEND, "bin", "ffprobe.exe"), "bin"),
]
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
    excludes=["tkinter", "matplotlib", "pymysql", "aiomysql"],
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
