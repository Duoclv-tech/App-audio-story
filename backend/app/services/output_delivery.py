"""Deliver finished artifacts to the user's configured output folder.

The output folder is configurable via the ``output_folder`` setting (Settings
tab) and defaults to the OS *Downloads* directory. Finished files are MOVED
(not copied) so the deliverable ends up only in the output folder.

This is safe because every place the app serves or previews these files reads
them by absolute path (``/api/v1/video/preview-audio?path=``,
``download-audio`` from the DB ``file_path``, the trim ``download`` endpoint
from the job's ``output_path``) — never through the ``/storage`` static mount.
So as long as we store the new path back in the DB / job, downloads and
previews keep working from the new location.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from loguru import logger

from app import models

OUTPUT_FOLDER_SETTING_KEY = "output_folder"


def default_output_folder() -> Path:
    """The fallback output folder: the current user's Downloads directory."""
    return Path.home() / "Downloads"


def get_output_folder(db) -> Path:
    """Resolve the configured output folder, falling back to ~/Downloads.

    Always returns an existing directory (creates it if needed).
    """
    folder: Optional[Path] = None
    try:
        row = (
            db.query(models.Setting)
            .filter(models.Setting.setting_key == OUTPUT_FOLDER_SETTING_KEY)
            .first()
        )
        val = row.setting_value if row else None
        if isinstance(val, str):
            val = val.strip().strip('"')
            if val:
                folder = Path(val)
    except Exception as e:  # never let a bad setting break the pipeline
        logger.warning(f"[output] cannot read output_folder setting: {e}")

    if folder is None:
        folder = default_output_folder()

    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"[output] cannot use folder {folder}: {e}; using Downloads")
        folder = default_output_folder()
        folder.mkdir(parents=True, exist_ok=True)

    return folder


def _unique_dest(dest: Path) -> Path:
    """Return a non-colliding destination path (appends ' (1)', ' (2)', ...)."""
    if not dest.exists():
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def deliver_final(src: str, db, filename: Optional[str] = None) -> str:
    """Move a finished file into the output folder and return the new path.

    Best-effort: on any failure the original ``src`` path is returned unchanged
    so a delivery problem never fails the whole pipeline.

    Args:
        src: absolute path of the finished file (inside ``storage/``).
        db: SQLAlchemy session used to read the output_folder setting.
        filename: desired file name in the output folder. Defaults to the
            source file name. Pass a story-aware name (e.g. ``"Tên truyện.mp3"``)
            to avoid generic names like ``merged_audio.mp3`` colliding.
    """
    try:
        src_path = Path(src)
        if not src_path.exists():
            return src
        folder = get_output_folder(db)
        dest = _unique_dest(folder / (filename or src_path.name))
        if src_path.resolve() == dest.resolve():
            return str(dest)
        shutil.move(str(src_path), str(dest))
        logger.info(f"[output] delivered -> {dest}")
        return str(dest)
    except Exception as e:
        logger.warning(f"[output] delivery failed for {src}: {e}")
        return src


def safe_file_stem(name: str, fallback: str = "output") -> str:
    """Strip characters Windows/most filesystems reject from a file stem."""
    cleaned = "".join(c for c in (name or "") if c not in '\\/:*?"<>|').strip()
    return cleaned or fallback
