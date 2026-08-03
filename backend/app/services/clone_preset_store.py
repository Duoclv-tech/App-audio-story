"""
Clone-voice preset store for the OmniVoice engine.

A preset is a folder under ``paths.CLONE_PRESETS_DIR`` holding a reference audio
sample + its transcript + meta.json. Used by OmniVoice "clone" mode so a cloned
voice can be reused across stories without re-uploading the sample each time.
Ported from the standalone omivoice-tts server.
"""
import json
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from app import paths

PRESETS_DIR = paths.CLONE_PRESETS_DIR
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    return s or "preset"


def _safe_audio_suffix(filename: Optional[str]) -> str:
    ext = Path(filename or "").suffix.lower()
    return ext if ext in ALLOWED_AUDIO_EXTS else ".wav"


def _preset_path(preset_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", preset_id or ""):
        raise HTTPException(400, "invalid preset_id")
    return PRESETS_DIR / preset_id


async def _save_upload_streaming(upload: UploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with dest.open("wb") as f:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"reference audio too large (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
                f.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise


def seed_default_presets() -> None:
    """Copy bundled default clone presets into the writable dir (once).

    Idempotent: only copies a preset folder that doesn't already exist, so the
    user can rename/delete a seeded preset without it reappearing on next call.
    A tiny marker file records which defaults were seeded so a user-deleted
    default stays deleted.
    """
    src_root = paths.DEFAULT_CLONE_PRESETS_DIR
    if not src_root.is_dir():
        return
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    marker = PRESETS_DIR / ".seeded_defaults"
    seeded = set(marker.read_text(encoding="utf-8").split("\n")) if marker.exists() else set()
    newly = []
    for src in sorted(src_root.iterdir()):
        if not src.is_dir() or not (src / "meta.json").exists():
            continue
        if src.name in seeded:
            continue  # already seeded once — respect later user deletion
        dest = PRESETS_DIR / src.name
        if not dest.exists():
            try:
                shutil.copytree(src, dest)
            except Exception:
                continue
        newly.append(src.name)
    if newly:
        marker.write_text("\n".join(sorted(seeded | set(newly))), encoding="utf-8")


def list_presets() -> List[Dict]:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    seed_default_presets()
    items: List[Dict] = []
    for p in sorted(PRESETS_DIR.iterdir()):
        if not p.is_dir():
            continue
        meta_path = p / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        audio_name = meta.get("audio_file")
        if not audio_name or not (p / audio_name).exists():
            continue
        items.append({
            "id": p.name,
            "name": meta.get("name", p.name),
            "audio_file": audio_name,
            "ref_text": meta.get("ref_text", ""),
            "created_at": meta.get("created_at"),
        })
    return items


def get_preset_name(preset_id: Optional[str]) -> Optional[str]:
    """Best-effort display name for a clone preset id, read straight from its
    meta.json (no dir scan / seeding side effects). Returns None for an invalid,
    missing, or unreadable preset — callers use this for labels only, so a miss
    just falls back to showing the raw id or nothing."""
    if not preset_id or not re.fullmatch(r"[a-zA-Z0-9_-]+", preset_id):
        return None
    meta_path = PRESETS_DIR / preset_id / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return meta.get("name") or preset_id


def _load_meta(preset_id: str) -> Tuple[Path, Path, Dict]:
    preset_dir = _preset_path(preset_id)
    meta_path = preset_dir / "meta.json"
    if not preset_dir.is_dir() or not meta_path.exists():
        raise HTTPException(404, "preset not found")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(500, "preset metadata is invalid")
    return preset_dir, meta_path, meta


def resolve_audio_and_text(preset_id: str) -> Tuple[str, str]:
    """Return (absolute_audio_path, ref_text) for a preset; raise if incomplete."""
    preset_dir, _meta_path, meta = _load_meta(preset_id)
    audio_name = meta.get("audio_file")
    ref_text = meta.get("ref_text")
    if not audio_name or not ref_text:
        raise HTTPException(500, "preset is incomplete")
    audio_path = preset_dir / audio_name
    if not audio_path.exists():
        raise HTTPException(500, "preset audio file not found")
    return str(audio_path), ref_text


async def save_preset(name: str, ref_text: str, ref_audio: UploadFile) -> Dict:
    if not name.strip():
        raise HTTPException(400, "name is required")
    if not ref_text.strip():
        raise HTTPException(400, "ref_text is required")
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    preset_id = f"{_slugify(name)}-{int(time.time())}"
    preset_dir = PRESETS_DIR / preset_id
    preset_dir.mkdir(parents=True, exist_ok=False)
    try:
        audio_name = f"reference{_safe_audio_suffix(ref_audio.filename)}"
        await _save_upload_streaming(ref_audio, preset_dir / audio_name)
        meta = {
            "id": preset_id, "name": name.strip(), "audio_file": audio_name,
            "ref_text": ref_text.strip(), "created_at": int(time.time()),
        }
        (preset_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(preset_dir, ignore_errors=True)
        raise
    return meta


def delete_preset(preset_id: str) -> None:
    preset_dir = _preset_path(preset_id)
    if not preset_dir.is_dir():
        raise HTTPException(404, "preset not found")
    shutil.rmtree(preset_dir)


def get_audio_path(preset_id: str) -> Path:
    preset_dir, _meta_path, meta = _load_meta(preset_id)
    audio_name = meta.get("audio_file")
    if not audio_name:
        raise HTTPException(500, "preset audio is missing")
    audio_path = preset_dir / audio_name
    if not audio_path.exists():
        raise HTTPException(404, "preset audio file not found")
    return audio_path
