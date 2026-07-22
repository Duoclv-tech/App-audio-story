"""
Persistence for the activated license.

Stored as a small JSON file in the writable per-user data dir (survives app
restart and reinstall of the tool as long as %LOCALAPPDATA% is preserved).
Holds the signed token (for offline verify) plus a little metadata for the UI.
"""
import json
from typing import Optional

from loguru import logger

from app import paths

_LICENSE_FILE = paths.DATA_DIR / "license.json"


def load() -> Optional[dict]:
    """Return the stored license record, or None if not activated yet."""
    try:
        if _LICENSE_FILE.is_file():
            return json.loads(_LICENSE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Could not read license file: {exc}")
    return None


def save(record: dict) -> None:
    """Persist the license record (token + metadata)."""
    try:
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _LICENSE_FILE.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.error(f"Could not write license file: {exc}")
        raise


def clear() -> None:
    """Remove the stored license (used for deactivation / testing)."""
    try:
        if _LICENSE_FILE.is_file():
            _LICENSE_FILE.unlink()
    except Exception as exc:
        logger.warning(f"Could not remove license file: {exc}")
