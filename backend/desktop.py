"""
Desktop entry point for TruyenFull Processor.

Runs the FastAPI app with uvicorn in a background thread bound to a free
localhost port, waits until it answers /health, then opens a native window
(Windows WebView2 via pywebview) pointing at it. Closing the window shuts the
server down.

Run in dev:   python desktop.py
When frozen:  this module is the PyInstaller entry point.
"""
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Force production behaviour BEFORE app.config is imported: no uvicorn reload,
# no SQLAlchemy echo. Env vars take priority over any .env file.
os.environ.setdefault("DEBUG", "release")

# Use the OS (Windows) certificate store for ALL outbound HTTPS instead of the
# bundled certifi CA list. On machines behind antivirus/corporate TLS proxies
# the interceptor's root CA lives in the Windows store but NOT in certifi, so
# requests-based calls (Gemini/OpenAI spellcheck, VBEE cloud TTS, HuggingFace
# model downloads) would otherwise fail with CERTIFICATE_VERIFY_FAILED. Must run
# before app.main / any HTTPS call. truststore is already bundled.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass  # fall back to certifi if truststore is unavailable

from app import paths
paths.setup_ffmpeg_path()
paths.hide_subprocess_windows()  # no console-window flashes from ffmpeg/ffprobe

# A windowed PyInstaller build has NO console: sys.stdout/stderr are None.
# Any library that writes there (loguru, uvicorn, print) would crash with
# "Cannot log to objects of type 'NoneType'". Redirect them to a log file
# BEFORE importing app.main (which configures loguru).
if sys.stdout is None or sys.stderr is None:
    try:
        _logf = open(paths.LOG_DIR / "desktop.out.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        import io
        _logf = io.StringIO()
    if sys.stdout is None:
        sys.stdout = _logf
    if sys.stderr is None:
        sys.stderr = _logf

import uvicorn
from loguru import logger

# Import the app object directly (not via the "app.main:app" string) so
# PyInstaller's static analysis detects app.main and all its routers/services
# as dependencies and bundles them.
from app.main import app as fastapi_app

WINDOW_TITLE = "TruyenFull Processor"


class NativeApi:
    """Exposed to the web page as ``window.pywebview.api``.

    Lets the React UI open the **native Windows** file/folder pickers instead of
    the in-app HTML browser. Every method returns the selected absolute path as a
    string, or ``None`` if the user cancels. When the app runs in a plain browser
    (dev), ``window.pywebview`` is absent and the UI falls back to the HTML browser.
    """

    _AUDIO_TYPES = (
        "Audio Files (*.mp3;*.wav;*.m4a;*.aac;*.flac;*.ogg)",
        "All files (*.*)",
    )
    _IMAGE_TYPES = (
        "Image Files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif)",
        "All files (*.*)",
    )
    _TEXT_TYPES = (
        "Text / Document (*.txt;*.docx)",
        "All files (*.*)",
    )

    def _window(self):
        import webview
        return webview.windows[0] if webview.windows else None

    def pick_folder(self, start: str = ""):
        import webview
        w = self._window()
        if w is None:
            return None
        directory = start if (start and Path(start).is_dir()) else ""
        result = w.create_file_dialog(webview.FileDialog.FOLDER, directory=directory)
        return result[0] if result else None

    def pick_audio_file(self, start: str = ""):
        return self._pick_file(start, self._AUDIO_TYPES)

    def pick_image_file(self, start: str = ""):
        return self._pick_file(start, self._IMAGE_TYPES)

    def pick_text_file(self, start: str = ""):
        return self._pick_file(start, self._TEXT_TYPES)

    def _pick_file(self, start: str, file_types):
        import webview
        w = self._window()
        if w is None:
            return None
        # ``start`` may be a file path or a directory; open in its containing dir.
        directory = ""
        if start:
            p = Path(start)
            cand = p if p.is_dir() else p.parent
            if cand.is_dir():
                directory = str(cand)
        result = w.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=directory,
            allow_multiple=False,
            file_types=file_types,
        )
        return result[0] if result else None


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BackendServer:
    """uvicorn server running in a daemon thread."""

    def __init__(self, port: int):
        self.port = port
        config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            reload=False,
            workers=1,
        )
        self.server = uvicorn.Server(config)
        # uvicorn installs signal handlers only in the main thread; disable so
        # running inside a worker thread doesn't raise.
        self.server.install_signal_handlers = lambda: None
        self._thread = threading.Thread(target=self.server.run, daemon=True, name="uvicorn")

    def start(self) -> None:
        self._thread.start()

    def wait_until_ready(self, timeout: float = 45.0) -> bool:
        url = f"http://127.0.0.1:{self.port}/health"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(0.4)
        return False

    def stop(self) -> None:
        self.server.should_exit = True
        self._thread.join(timeout=10)


def selftest() -> int:
    """Start the backend, verify a few endpoints, and exit — no GUI.

    Used to smoke-test a frozen build: proves PyInstaller bundled the frontend,
    ffmpeg, sqlite and all hidden imports correctly. Run: TruyenFullProcessor.exe --selftest
    """
    # Disable the license gate for this in-process smoke test only, so protected
    # routes (e.g. /tts/voices) can be checked without a real activation.
    from app.license import service as _license_service
    _license_service.set_selftest_mode(True)

    port = _find_free_port()
    server = BackendServer(port)
    server.start()
    ok = server.wait_until_ready(timeout=45)
    base = f"http://127.0.0.1:{port}"

    def _get(path):
        try:
            with urllib.request.urlopen(base + path, timeout=5) as r:
                return r.status, r.read()
        except Exception:
            return 0, b""

    checks = []
    try:
        checks.append(("backend_ready", ok))
        checks.append(("health", _get("/health")[0] == 200))
        checks.append(("frontend_index", b"doctype html" in _get("/")[1].lower()))
        checks.append(("api_voices", b"ngochuyen" in _get("/api/v1/tts/voices")[1]))
        import shutil
        checks.append(("ffmpeg_resolvable", bool(shutil.which("ffmpeg"))))
    finally:
        server.stop()

    lines = ["SELFTEST RESULTS:"]
    all_ok = True
    for name, passed in checks:
        lines.append(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        all_ok = all_ok and passed
    lines.append("SELFTEST " + ("OK" if all_ok else "FAILED"))
    report = "\n".join(lines)
    print(report)
    # Also write to a file so a windowed (no-console) frozen build is verifiable.
    try:
        (paths.DATA_DIR / "selftest_result.txt").write_text(report, encoding="utf-8")
    except Exception:
        pass
    return 0 if all_ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    port = _find_free_port()
    logger.info(f"Starting backend on 127.0.0.1:{port}")
    server = BackendServer(port)
    server.start()

    if not server.wait_until_ready():
        logger.error("Backend did not become ready in time")
        # Fall through and still open the window so the user sees an error page
        # rather than nothing.

    import webview  # imported late so headless server tests don't need a GUI

    url = f"http://127.0.0.1:{port}/"
    # js_api exposes native OS file/folder pickers to the page (window.pywebview.api).
    webview.create_window(
        WINDOW_TITLE, url, js_api=NativeApi(),
        width=1400, height=900, min_size=(1000, 700),
        text_select=True,  # pywebview disables page text selection by default;
                           # enable it so users can drag-select & copy any text.
    )
    try:
        webview.start()  # blocks until the window is closed
    finally:
        logger.info("Window closed, shutting down backend")
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
