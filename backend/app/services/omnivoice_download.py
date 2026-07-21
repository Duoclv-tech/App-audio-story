"""
OmniVoice model download manager.

Models are large (several GB) so they aren't bundled in the .exe — they're
pulled from HuggingFace into the writable models dir at install / first run.
Runs in a background thread with an in-memory status (state + byte progress)
the UI polls to render a download progress bar.
"""
import os
import threading
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

from app import paths
from app.config import settings

# key -> (repo_id, local_dir). Only the base model is used now.
_TARGETS = {
    "base": (settings.OMNIVOICE_BASE_REPO, settings.OMNIVOICE_BASE_PATH),
}

# The main weights file — its presence means the model is actually usable.
# (config.json arrives first and is tiny, so it's a poor readiness signal.)
_READY_FILE = "model.safetensors"

# per-key download state
_status: Dict[str, Dict] = {
    key: {"state": "idle", "error": "", "path": path,
          "total_bytes": 0, "downloaded_bytes": 0}
    for key, (_repo, path) in _TARGETS.items()
}
_lock = threading.Lock()


def _dir_size(path: str) -> int:
    total = 0
    p = Path(path)
    if not p.exists():
        return 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _is_downloaded(key: str) -> bool:
    """True only when the actual weights file is present (not just config)."""
    _repo, path = _TARGETS[key]
    return (Path(path) / _READY_FILE).exists()


def get_status(key: str) -> Dict:
    if key not in _TARGETS:
        return {"state": "unknown", "error": f"unknown model key: {key}"}
    st = dict(_status[key])
    st["downloaded"] = _is_downloaded(key)
    total = st.get("total_bytes") or 0
    done = st.get("downloaded_bytes") or 0
    st["percent"] = round(min(100.0, done / total * 100), 1) if total else None
    return st


def get_all_status() -> Dict[str, Dict]:
    return {key: get_status(key) for key in _TARGETS}


def _fetch_total_bytes(repo_id: str) -> int:
    """Best-effort total repo size (sum of file sizes) for the progress bar."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().repo_info(repo_id=repo_id, files_metadata=True)
        return sum((s.size or 0) for s in (info.siblings or []))
    except Exception as e:
        logger.warning(f"[omnivoice] could not fetch total size for {repo_id}: {e}")
        return 0


def _progress_poller(key: str, local_dir: str, stop: threading.Event) -> None:
    """Update downloaded_bytes from the on-disk size while downloading."""
    while not stop.is_set():
        size = _dir_size(local_dir)
        with _lock:
            _status[key]["downloaded_bytes"] = size
        stop.wait(1.5)


def _do_download(key: str) -> None:
    repo_id, local_dir = _TARGETS[key]
    stop = threading.Event()
    poller = threading.Thread(target=_progress_poller, args=(key, local_dir, stop), daemon=True)
    try:
        import truststore
        truststore.inject_into_ssl()
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        from huggingface_hub import snapshot_download

        total = _fetch_total_bytes(repo_id)
        with _lock:
            _status[key]["total_bytes"] = total
        logger.info(f"[omnivoice] downloading {repo_id} -> {local_dir} "
                    f"(total {total/1024/1024:.0f} MB)")
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        poller.start()
        snapshot_download(repo_id=repo_id, local_dir=str(local_dir))
        with _lock:
            _status[key]["state"] = "done"
            _status[key]["error"] = ""
            _status[key]["downloaded_bytes"] = _dir_size(local_dir)
            if not _status[key]["total_bytes"]:
                _status[key]["total_bytes"] = _status[key]["downloaded_bytes"]
        logger.info(f"[omnivoice] downloaded {key}")
    except Exception as e:
        logger.error(f"[omnivoice] download failed for {key}: {e}")
        with _lock:
            _status[key]["state"] = "error"
            _status[key]["error"] = str(e)
    finally:
        stop.set()


def start_download(key: str) -> Dict:
    """Kick off a background download (idempotent while running/done)."""
    if key not in _TARGETS:
        raise ValueError(f"unknown model key: {key}")
    with _lock:
        if _is_downloaded(key):
            _status[key]["state"] = "done"
            return get_status(key)
        if _status[key]["state"] == "downloading":
            return get_status(key)
        _status[key]["state"] = "downloading"
        _status[key]["error"] = ""
        _status[key]["downloaded_bytes"] = 0
    t = threading.Thread(target=_do_download, args=(key,), daemon=True)
    t.start()
    return get_status(key)
