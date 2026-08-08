#!/usr/bin/env bash
# Build the AudioStory Linux desktop app (VBEE-only) locally.
#
# Mirrors .github/workflows/build-ubuntu.yml for people building on their own
# Ubuntu machine. Produces dist/AudioStory/AudioStory and a
# dist/AudioStory-linux-x86_64.tar.gz.
#
# One-time system deps (Ubuntu 22.04/24.04):
#   sudo apt-get install -y libgirepository1.0-dev libcairo2-dev pkg-config \
#     gobject-introspection gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0
#
# Usage:  ./packaging/build-linux.sh [--skip-frontend]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$REPO/backend"
VENV="$BACKEND/venv"

SKIP_FRONTEND=0
[[ "${1:-}" == "--skip-frontend" ]] && SKIP_FRONTEND=1

step() { printf '\n=== %s ===\n' "$1"; }

# --- 1. Frontend -----------------------------------------------------------
if [[ $SKIP_FRONTEND -eq 0 ]]; then
  step "1/4 Build frontend (vite)"
  ( cd "$REPO/frontend" && { [[ -d node_modules ]] || npm ci; } && npm run build )
else
  step "1/4 Frontend — SKIPPED"
fi

# --- 2. Python venv + deps -------------------------------------------------
step "2/4 Python venv + deps"
[[ -d "$VENV" ]] || python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip wheel >/dev/null
pip install -r "$BACKEND/requirements.txt"
pip install "pywebview[gtk]"
pip install "pyinstaller==6.11.1"

# --- 2b. Static ffmpeg -----------------------------------------------------
if [[ ! -x "$BACKEND/bin_linux/ffmpeg" ]]; then
  step "Fetch static ffmpeg"
  mkdir -p "$BACKEND/bin_linux"
  tmp="$(mktemp -d)"
  curl -L -o "$tmp/ffmpeg.tar.xz" \
    https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
  tar -xf "$tmp/ffmpeg.tar.xz" -C "$tmp"
  d="$(find "$tmp" -maxdepth 1 -type d -name 'ffmpeg-*-amd64-static' | head -n1)"
  cp "$d/ffmpeg" "$d/ffprobe" "$BACKEND/bin_linux/"
  chmod +x "$BACKEND/bin_linux/ffmpeg" "$BACKEND/bin_linux/ffprobe"
  rm -rf "$tmp"
fi

# --- 3. PyInstaller --------------------------------------------------------
step "3/4 PyInstaller (Linux VBEE-only)"
pyinstaller "$REPO/packaging/audiostory_linux.spec" --noconfirm \
  --distpath "$REPO/dist" --workpath "$REPO/build"

# --- 3b. Self-test (headless) ---------------------------------------------
step "Self-test"
"$REPO/dist/AudioStory/AudioStory" --selftest

# --- 4. Package ------------------------------------------------------------
step "4/4 Package tarball"
( cd "$REPO/dist" && tar -czf AudioStory-linux-x86_64.tar.gz AudioStory )
echo "Done: $REPO/dist/AudioStory-linux-x86_64.tar.gz"
