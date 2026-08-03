import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from loguru import logger
from typing import List

from app.database import get_db
from app import models, schemas
from app.api.video import require_localhost
from app.services import build_orchestrator, gpu_guard, clone_preset_store
from app.workers import tts_worker

router = APIRouter()

_STORY_EXTS = (".txt", ".docx")


def _wizard_gpu_busy(db: Session) -> bool:
    """True if a wizard GPU task (video render or OmniVoice TTS) is in flight —
    a batch must not start on top of it. The reverse (wizard-vs-batch) is guarded
    by gpu_guard.is_busy() in the wizard endpoints."""
    video = db.query(models.Task).filter(
        models.Task.type == "video_processing",
        models.Task.status.in_(["queued", "running"]),
    ).first()
    if video:
        return True
    omni_tts = db.query(models.Task).filter(
        models.Task.type.in_(["tts", "tts_merged"]),
        models.Task.engine == "omnivoice",
        models.Task.status.in_(["queued", "running"]),
    ).first()
    if omni_tts:
        return True
    # OmniVoice per-segment generation tracks itself in-memory, not via Task rows.
    return tts_worker.any_story_active()


def _preset_or_404(db: Session, preset_id: str) -> models.BuildPreset:
    preset = db.query(models.BuildPreset).filter(models.BuildPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Build preset không tồn tại")
    return preset


def _build_config_snapshot(preset: models.BuildPreset, common_overrides: dict | None) -> dict:
    """Freeze the effective build config so the history feed can show the exact
    settings used, even after the preset is later edited or deleted. Batch-level
    preset values, plus the per-run common toggles (auto_clean / auto_subtitle /
    video_folder) that Quick Build applies to every job."""
    tts = preset.tts_config or {}
    opts = preset.options or {}
    ov = common_overrides or {}
    engine = tts.get("engine") or "vbee"
    # OmniVoice identifies its voice by mode (auto/design/clone), not voice_code.
    # For clone mode, freeze the human-readable preset name (a per-job override
    # wins, mirroring the other snapshot fields) so history shows the actual voice.
    mode = (tts.get("mode") or "auto") if engine == "omnivoice" else None
    clone_id = ov.get("clone_preset_id") or tts.get("preset_id")
    clone_preset_name = (clone_preset_store.get_preset_name(clone_id)
                         if engine == "omnivoice" and mode == "clone" else None)
    return {
        "preset_name": preset.name,
        "engine": engine,
        "voice_code": tts.get("voice_code"),
        "mode": mode,
        "clone_preset_name": clone_preset_name,
        "speed": tts.get("speed"),
        "resolution": (preset.video_cfg or {}).get("resolution"),
        "video_folder": ov.get("video_folder") or preset.video_folder,
        "has_bgm": bool(preset.bgm_path),
        "skip_spellcheck": bool(opts.get("skip_spellcheck", True)),
        "auto_clean": ov.get("auto_clean") if ov.get("auto_clean") is not None
                      else bool(opts.get("auto_clean", False)),
        "auto_subtitle": ov.get("auto_subtitle") if ov.get("auto_subtitle") is not None
                         else bool(opts.get("auto_subtitle", False)),
    }


@router.post("/scan-folder", response_model=List[schemas.QuickBuildScanItem],
             dependencies=[Depends(require_localhost)])
async def scan_folder(req: schemas.QuickBuildScanRequest):
    """List story files (.txt/.docx) in a folder, flagging a same-named image
    that would auto-fill the banner."""
    path = req.path
    if not path or not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Không tìm thấy thư mục")

    items: List[schemas.QuickBuildScanItem] = []
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if not os.path.isfile(full):
                continue
            if os.path.splitext(name)[1].lower() not in _STORY_EXTS:
                continue
            items.append(schemas.QuickBuildScanItem(
                source_path=full,
                title=build_orchestrator._nice_title(full),
                has_banner=build_orchestrator.has_sibling_banner(full),
            ))
    except Exception as e:
        logger.error(f"[quick-build] scan folder failed ({path}): {e}")
        raise HTTPException(status_code=400, detail="Không đọc được thư mục")

    if not items:
        raise HTTPException(status_code=400, detail="Thư mục không có file .txt hoặc .docx nào")
    return items


def _acquire_gpu_or_409(db: Session) -> None:
    """Take the GPU guard for a batch, refusing if the GPU is already in use by
    another batch or a wizard render/TTS. Both directions are covered.

    Try-acquire first so a second batch gets the accurate 'batch đang chạy'
    message; then check wizard tasks and release if one is mid-run."""
    if not gpu_guard.try_acquire():
        raise HTTPException(status_code=409, detail="Đang có batch khác chạy — vui lòng đợi.")
    if _wizard_gpu_busy(db):
        gpu_guard.release()
        raise HTTPException(status_code=409,
                            detail="Đang render/đọc TTS ở màn hình khác — vui lòng đợi xong.")


@router.post("/start", dependencies=[Depends(require_localhost)])
async def start_batch(req: schemas.QuickBuildStartRequest, db: Session = Depends(get_db)):
    """Create a batch from the selected files and start it in the background."""
    _preset_or_404(db, req.preset_id)

    selected = [j for j in req.jobs if j.selected]
    if not selected:
        raise HTTPException(status_code=400, detail="Chưa chọn truyện nào để build")

    # Fail fast on missing clip folders BEFORE running anything — resolve each
    # job's effective preset (per-job override or the batch preset) and folder.
    preset_cache: dict = {}
    for j in selected:
        pid = (j.overrides or {}).get("preset_id") or req.preset_id
        if pid not in preset_cache:
            preset_cache[pid] = _preset_or_404(db, pid)
        folder = (j.overrides or {}).get("video_folder") or preset_cache[pid].video_folder
        if not folder:
            raise HTTPException(status_code=400,
                                detail=f"Preset của '{j.title or os.path.basename(j.source_path)}' chưa có folder clip nền")

    # GPU guard is the last gate — take it synchronously so two near-simultaneous
    # starts can't both pass (the worker thread inherits ownership).
    _acquire_gpu_or_409(db)
    try:
        # Freeze the batch-level config from its preset + the common per-run
        # toggles (carried identically on every job's overrides).
        snapshot = _build_config_snapshot(preset_cache[req.preset_id], selected[0].overrides) \
            if req.preset_id in preset_cache else \
            _build_config_snapshot(_preset_or_404(db, req.preset_id), selected[0].overrides)
        batch = models.BuildBatch(status="queued", total=len(selected),
                                  config_snapshot=snapshot)
        db.add(batch)
        db.commit()
        db.refresh(batch)

        for i, j in enumerate(selected):
            job_preset_id = (j.overrides or {}).get("preset_id") or req.preset_id
            db.add(models.BuildJob(
                batch_id=batch.id,
                order_index=i,
                source_path=j.source_path,
                title=j.title or build_orchestrator._nice_title(j.source_path),
                preset_id=job_preset_id,
                overrides=j.overrides or None,
                stage="create",
                status="pending",
            ))
        db.commit()
        build_orchestrator.start_batch_thread(batch.id)
    except Exception:
        gpu_guard.release()
        raise

    logger.info(f"[quick-build] started batch {batch.id} with {len(selected)} job(s)")
    return {"batch_id": batch.id, "total": len(selected)}


def _job_progress(db: Session, job: models.BuildJob) -> int:
    """Live 0-100 for a job. Done = 100; a running 'video' job mirrors its video
    Task.progress (updated in real time by the ffmpeg encoder); everything else 0."""
    if job.status == "done":
        return 100
    if job.status == "running" and job.stage == "video" and job.story_id:
        task = db.query(models.Task).filter(
            models.Task.story_id == job.story_id,
            models.Task.type == "video_processing",
        ).order_by(models.Task.created_at.desc()).first()
        if task and task.progress:
            return max(0, min(100, int(task.progress)))
    return 0


@router.get("/{batch_id}/status", response_model=schemas.QuickBuildBatchStatus,
            dependencies=[Depends(require_localhost)])
async def batch_status(batch_id: str, db: Session = Depends(get_db)):
    batch = db.query(models.BuildBatch).filter(models.BuildBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch không tồn tại")
    jobs = db.query(models.BuildJob).filter(
        models.BuildJob.batch_id == batch_id
    ).order_by(models.BuildJob.order_index).all()

    out = []
    for j in jobs:
        size = None
        if j.output_path and os.path.exists(j.output_path):
            try:
                size = os.path.getsize(j.output_path)
            except OSError:
                size = None
        out.append(schemas.QuickBuildJobOut(
            id=j.id, order_index=j.order_index, source_path=j.source_path,
            title=j.title, story_id=j.story_id, stage=j.stage, status=j.status,
            progress=_job_progress(db, j), output_path=j.output_path,
            output_size=size, error_message=j.error_message, updated_at=j.updated_at,
        ))
    return schemas.QuickBuildBatchStatus(
        id=batch.id, status=batch.status, total=batch.total, jobs=out
    )


@router.post("/{batch_id}/stop", dependencies=[Depends(require_localhost)])
async def stop_batch(batch_id: str, db: Session = Depends(get_db)):
    batch = db.query(models.BuildBatch).filter(models.BuildBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch không tồn tại")
    build_orchestrator.stop_batch(batch_id)
    return {"message": "Đã yêu cầu dừng — job đang render sẽ chạy nốt rồi dừng."}


@router.post("/job/{job_id}/cancel", dependencies=[Depends(require_localhost)])
async def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """Drop a still-queued job from the batch. Only 'pending' jobs can be cancelled —
    a running render can't be interrupted; the batch loop re-checks status and skips it."""
    job = db.query(models.BuildJob).filter(models.BuildJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail="Chỉ bỏ được job đang chờ")
    job.status = "skipped"
    job.error_message = "Đã bỏ khỏi hàng đợi"
    db.commit()
    return {"message": "Đã bỏ job khỏi hàng đợi"}


@router.post("/job/{job_id}/retry", dependencies=[Depends(require_localhost)])
async def retry_job(job_id: str, db: Session = Depends(get_db)):
    """Re-run a single failed file as a fresh 1-job batch (new Story, clean state)."""
    job = db.query(models.BuildJob).filter(models.BuildJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    # Same full GPU guard as start (start had it, retry used to skip half of it).
    _acquire_gpu_or_409(db)
    try:
        retry_preset = db.query(models.BuildPreset).filter(
            models.BuildPreset.id == job.preset_id
        ).first() if job.preset_id else None
        snapshot = _build_config_snapshot(retry_preset, job.overrides) if retry_preset else None
        batch = models.BuildBatch(status="queued", total=1, config_snapshot=snapshot)
        db.add(batch)
        db.commit()
        db.refresh(batch)
        db.add(models.BuildJob(
            batch_id=batch.id,
            order_index=0,
            source_path=job.source_path,
            title=job.title,
            preset_id=job.preset_id,
            overrides=job.overrides,
            stage="create",
            status="pending",
        ))
        db.commit()
        build_orchestrator.start_batch_thread(batch.id)
    except Exception:
        gpu_guard.release()
        raise
    return {"batch_id": batch.id, "total": 1}
