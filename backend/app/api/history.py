"""Unified history feed: standalone wizard stories and Quick Build batches in one
time-ordered list. A batch is one collapsible entry whose child jobs render as
compact rows; a standalone story (``batch_id IS NULL``) is a leaf entry that
carries the same stats the old flat history showed.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from loguru import logger

from app.database import get_db
from app import models
from app.api.video import require_localhost
from app.services import build_orchestrator, clone_preset_store

router = APIRouter()


def _story_with_stats(db: Session, story: models.Story) -> dict:
    """The exact shape the history rows expect (mirrors /stories/with-stats)."""
    total_downloaded = db.query(models.Chapter).filter(
        models.Chapter.story_id == story.id
    ).count()
    total_audio_generated = db.query(models.AudioFile).join(models.Chapter).filter(
        models.Chapter.story_id == story.id,
        models.AudioFile.status == "success",
    ).count()
    has_merged_audio = db.query(models.MergedAudio).filter(
        models.MergedAudio.story_id == story.id
    ).first() is not None
    return {
        "id": story.id,
        "title": story.title,
        "url": story.url,
        "author": story.author,
        "start_chapter": story.start_chapter,
        "end_chapter": story.end_chapter,
        "status": story.status,
        "current_step": story.current_step,
        "is_favorite": story.is_favorite,
        "created_at": story.created_at,
        "updated_at": story.updated_at,
        "total_downloaded": total_downloaded,
        "total_audio_generated": total_audio_generated,
        "has_merged_audio": has_merged_audio,
    }


def _config_from_preset(db: Session, preset_id) -> dict | None:
    """Reconstruct a config snapshot from the referenced preset for batches built
    before the snapshot column existed. Best-effort: reflects the preset's CURRENT
    state, so it can be stale if the preset was edited (or None if deleted)."""
    if not preset_id:
        return None
    p = db.query(models.BuildPreset).filter(models.BuildPreset.id == preset_id).first()
    if not p:
        return None
    tts = p.tts_config or {}
    opts = p.options or {}
    engine = tts.get("engine") or "vbee"
    mode = (tts.get("mode") or "auto") if engine == "omnivoice" else None
    clone_preset_name = (clone_preset_store.get_preset_name(tts.get("preset_id"))
                         if engine == "omnivoice" and mode == "clone" else None)
    return {
        "preset_name": p.name,
        "engine": engine,
        "voice_code": tts.get("voice_code"),
        "mode": mode,
        "clone_preset_name": clone_preset_name,
        "speed": tts.get("speed"),
        "resolution": (p.video_cfg or {}).get("resolution"),
        "video_folder": p.video_folder,
        "has_bgm": bool(p.bgm_path),
        "skip_spellcheck": bool(opts.get("skip_spellcheck", True)),
        "auto_clean": bool(opts.get("auto_clean", False)),
        "auto_subtitle": bool(opts.get("auto_subtitle", False)),
    }


def _batch_entry(db: Session, batch: models.BuildBatch) -> dict:
    jobs = db.query(models.BuildJob).filter(
        models.BuildJob.batch_id == batch.id
    ).order_by(models.BuildJob.order_index).all()

    done = sum(1 for j in jobs if j.status == "done")
    errored = sum(1 for j in jobs if j.status == "error")

    # Derive the header label from the jobs (no snapshot column needed): the
    # folder is the parent dir of the source files, the preset is the batch preset.
    source_folder = os.path.dirname(jobs[0].source_path) if jobs else None
    preset_id = next((j.preset_id for j in jobs if j.preset_id), None)

    # Frozen config chosen at build time. Batches created before the snapshot
    # column existed fall back to reading the referenced preset live (may be
    # stale/missing if the preset was since edited or deleted).
    config = batch.config_snapshot or _config_from_preset(db, preset_id)
    preset_name = config.get("preset_name") if config else None

    job_rows = []
    for j in jobs:
        has_output = bool(j.output_path and os.path.exists(j.output_path))
        job_rows.append({
            "id": j.id,
            "order_index": j.order_index,
            "title": j.title,
            "story_id": j.story_id,
            "stage": j.stage,
            "status": j.status,
            "output_path": j.output_path,
            "has_output": has_output,
            "error_message": j.error_message,
        })

    return {
        "id": batch.id,
        "status": batch.status,
        "total": batch.total,
        "done_count": done,
        "error_count": errored,
        "source_folder": source_folder,
        "folder_label": os.path.basename(source_folder) if source_folder else None,
        "preset_name": preset_name,
        "config": config,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "jobs": job_rows,
    }


@router.get("/feed")
async def history_feed(
    page: int = 1,
    page_size: int = 20,
    favorite_only: bool = False,
    db: Session = Depends(get_db),
):
    """Time-ordered feed of standalone stories + Quick Build batches (paginated).

    ``favorite_only`` narrows to favourite standalone stories and drops batches
    (a batch can't be favourited), matching the existing filter's intent.
    """
    try:
        skip = (page - 1) * page_size

        story_count = db.query(models.Story).filter(
            models.Story.batch_id.is_(None),
            *( [models.Story.is_favorite == True] if favorite_only else [] ),
        ).count()

        if favorite_only:
            total = story_count
            keys = db.execute(text(
                "SELECT id, 'story' AS kind, updated_at AS ts FROM stories "
                "WHERE batch_id IS NULL AND is_favorite = 1 "
                "ORDER BY ts DESC LIMIT :limit OFFSET :offset"
            ), {"limit": page_size, "offset": skip}).all()
        else:
            batch_count = db.query(models.BuildBatch).count()
            total = story_count + batch_count
            keys = db.execute(text(
                "SELECT id, kind, ts FROM ("
                "  SELECT id AS id, 'story' AS kind, updated_at AS ts FROM stories WHERE batch_id IS NULL"
                "  UNION ALL"
                "  SELECT id AS id, 'batch' AS kind, updated_at AS ts FROM build_batches"
                ") feed ORDER BY ts DESC LIMIT :limit OFFSET :offset"
            ), {"limit": page_size, "offset": skip}).all()

        data = []
        for row in keys:
            if row.kind == "story":
                story = db.query(models.Story).filter(models.Story.id == row.id).first()
                if story:
                    data.append({"kind": "story", "story": _story_with_stats(db, story)})
            else:
                batch = db.query(models.BuildBatch).filter(
                    models.BuildBatch.id == row.id
                ).first()
                if batch:
                    data.append({"kind": "batch", "batch": _batch_entry(db, batch)})

        total_pages = (total + page_size - 1) // page_size
        return {
            "data": data,
            "meta": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            },
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error building history feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/batch/{batch_id}", dependencies=[Depends(require_localhost)])
async def delete_batch(batch_id: str, db: Session = Depends(get_db)):
    """Delete a whole batch: its jobs + the intermediate stories they created
    (chapters/audio cascade). The finished video files in the output folder are
    left untouched. Refuses while the batch is still running."""
    batch = db.query(models.BuildBatch).filter(models.BuildBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Mẻ không tồn tại")
    if build_orchestrator.is_batch_running(batch_id) or batch.status in ("queued", "running"):
        raise HTTPException(status_code=400, detail="Mẻ đang chạy — hãy dừng trước khi xoá.")

    try:
        jobs = db.query(models.BuildJob).filter(models.BuildJob.batch_id == batch_id).all()
        for job in jobs:
            if job.story_id:
                story = db.query(models.Story).filter(models.Story.id == job.story_id).first()
                if story:
                    db.delete(story)  # cascades chapters/audio like the story delete endpoint
        db.query(models.BuildJob).filter(models.BuildJob.batch_id == batch_id).delete()
        db.delete(batch)
        db.commit()
        logger.info(f"[history] deleted batch {batch_id} ({len(jobs)} job(s))")
        return {"message": "Đã xoá mẻ build", "id": batch_id}
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"[history] delete batch {batch_id} failed: {e}")
        raise HTTPException(status_code=500, detail="Không xoá được mẻ build")
