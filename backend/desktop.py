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

# Force production behaviour BEFORE app.config is imported: no uvicorn reload,
# no SQLAlchemy echo. Env vars take priority over any .env file.
os.environ.setdefault("DEBUG", "release")

from app import paths
paths.setup_ffmpeg_path()

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
    webview.create_window(WINDOW_TITLE, url, width=1400, height=900, min_size=(1000, 700))
    try:
        webview.start()  # blocks until the window is closed
    finally:
        logger.info("Window closed, shutting down backend")
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
