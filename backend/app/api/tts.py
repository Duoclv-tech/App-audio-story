import os

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Form, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from loguru import logger
from typing import List, Optional

from app.database import get_db
from app import models, schemas
from app.workers.tts_worker import process_tts_task

router = APIRouter()

DEFAULT_VBEE_VOICE = "hn_female_ngochuyen_full_48k-fhg"


def _delete_audio_file(file_path) -> None:
    """Best-effort removal of an audio file on disk (ignore if missing)."""
    if not file_path:
        return
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"[tts] could not delete orphan audio {file_path}: {e}")


def _build_tts_config(request: schemas.TTSRequest) -> dict:
    """Flatten a TTSRequest into the config dict the workers consume.

    Carries the engine selector plus both VBEE and OmniVoice fields so the
    worker can route without caring which UI tab produced the request.
    """
    return {
        "engine": (request.engine or "vbee").lower(),
        # VBEE / shared
        "voice_code": request.voice_code or DEFAULT_VBEE_VOICE,
        "audio_type": request.audio_type or "mp3",
        "bitrate": request.bitrate or 128,
        "speed": request.speed if request.speed else 1.0,
        # OmniVoice
        "mode": request.mode or "auto",
        "model_key": request.model_key or "base",
        "preset_id": request.preset_id,
        "ref_text": request.ref_text,
        "instruct": request.instruct,
        "language": request.language or "Auto",
    }


# ==================== OmniVoice (local TTS) ====================
# Declared BEFORE the parametrized /{task_id}/status route so /omnivoice/status
# isn't shadowed by it (FastAPI matches routes in definition order).

@router.get("/omnivoice/status")
async def omnivoice_status(db: Session = Depends(get_db)):
    """Whether the local OmniVoice engine can run (deps/GPU/model/CPU-mode) + download state."""
    from app.services import omnivoice_processor as ov
    from app.services import omnivoice_download as dl
    return {
        "availability": ov.availability(db),
        "downloads": dl.get_all_status(),
    }


@router.post("/omnivoice/download")
async def omnivoice_download(model_key: str = "base"):
    """Kick off (or report) a background model download from HuggingFace."""
    from app.services import omnivoice_download as dl
    try:
        return dl.start_download(model_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/omnivoice/presets")
async def omnivoice_list_presets():
    """List saved clone-voice presets."""
    from app.services import clone_preset_store as presets
    return {"presets": presets.list_presets()}


@router.post("/omnivoice/presets")
async def omnivoice_create_preset(
    name: str = Form(...),
    ref_text: str = Form(...),
    ref_audio: UploadFile = File(...),
):
    """Create a clone-voice preset from a reference sample + transcript."""
    from app.services import clone_preset_store as presets
    meta = await presets.save_preset(name, ref_text, ref_audio)
    return {"ok": True, "preset": meta}


@router.delete("/omnivoice/presets/{preset_id}")
async def omnivoice_delete_preset(preset_id: str):
    from app.services import clone_preset_store as presets
    presets.delete_preset(preset_id)
    return {"ok": True, "deleted": preset_id}


@router.get("/omnivoice/presets/{preset_id}/audio")
async def omnivoice_preset_audio(preset_id: str):
    from app.services import clone_preset_store as presets
    return FileResponse(presets.get_audio_path(preset_id))


@router.post("/start", response_model=schemas.TTSResponse)
async def start_tts(
    request: schemas.TTSRequest,
    db: Session = Depends(get_db)
):
    """Start TTS processing and wait for completion"""
    # Check if story exists
    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Create task
    task = models.Task(
        story_id=request.story_id,
        type="tts",
        status="running"
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Run TTS synchronously
    config = _build_tts_config(request)

    result = await process_tts_task(task.id, story.id, config)

    if result.get("success"):
        # Update story status and step after successful TTS
        story.status = "tts_completed"
        story.current_step = 6  # Move to Merge step
        db.commit()

        return {
            "task_id": task.id,
            "status": "completed",
            "message": f"Processed {result.get('audio_files_created', 0)} chapters successfully"
        }
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "TTS processing failed"))

@router.get("/{task_id}/status", response_model=schemas.TaskResponse)
async def get_tts_status(task_id: str, db: Session = Depends(get_db)):
    """Get TTS task status"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.get("/voices")
async def list_voices(db: Session = Depends(get_db)):
    """List available TTS voices from database"""
    # Query voices from database
    # Secondary sort by code: several voices share rank (e.g. four at rank=1),
    # so ordering by rank alone would return a nondeterministic first row.
    voices = db.query(models.Voice).filter(
        models.Voice.is_active == True
    ).order_by(models.Voice.rank, models.Voice.code).all()

    # Format response
    voices_list = [
        {
            "code": voice.code,
            "name": voice.name,
            "gender": voice.gender,
            "locale": voice.locale,
            "category": voice.category,
            "description": voice.description,
            "demo_url": voice.demo_url
        }
        for voice in voices
    ]

    logger.info(f"Retrieved {len(voices_list)} voices from database")
    return {"voices": voices_list}


# VBEE's own catalog is exactly Vietnamese + English (provider=vbee → 25 vi + 16
# en; every other language is a Google/Amazon/Microsoft voice the VBEE engine
# can't use). Filtering to provider=vbee keeps search results to voices this
# account can actually synthesize.
_VBEE_VOICES_URL = "https://vbee.vn/api/v1/voices"

# The provider=vbee catalog is small (~41) and effectively static, so cache it
# in-process instead of re-downloading on every search.
_VBEE_CATALOG_TTL = 300  # seconds
_vbee_catalog_cache: dict = {"at": 0.0, "voices": None}


def _strip_accents(s: str) -> str:
    """Lowercase + drop Vietnamese diacritics so "ngoc" matches "Ngọc".

    VBEE's own ``search`` param is diacritic-sensitive, which is poor UX for
    users typing without accents, so we filter locally instead.
    """
    import unicodedata

    s = (s or "").replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _fetch_vbee_catalog() -> list:
    """Return VBEE's provider=vbee voice list, cached for a few minutes.

    Raises ``requests.RequestException`` (network) or ``ValueError`` (bad shape)
    so the caller can turn either into a graceful 502.
    """
    import time
    import requests

    now = time.monotonic()
    cached = _vbee_catalog_cache["voices"]
    if cached is not None and now - _vbee_catalog_cache["at"] < _VBEE_CATALOG_TTL:
        return cached

    resp = requests.get(_VBEE_VOICES_URL, params={"provider": "vbee"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    result = data.get("result") if isinstance(data, dict) else None
    voices = result.get("voices") if isinstance(result, dict) else None
    if not isinstance(voices, list):
        raise ValueError("unexpected VBEE voices payload")

    _vbee_catalog_cache["voices"] = voices
    _vbee_catalog_cache["at"] = now
    return voices


# Plain ``def`` (not ``async``): FastAPI runs sync path operations in a
# threadpool, so the blocking requests.get here never freezes the event loop.
@router.get("/voices/search")
def search_vbee_voices(q: str = "", limit: int = 30):
    """Search VBEE's live voice catalog (Vietnamese + English only).

    Thin proxy over the public ``GET https://vbee.vn/api/v1/voices`` endpoint so
    the UI can offer voices beyond the 25 seeded in the DB without us storing
    them. ``provider=vbee`` is only ~41 voices, so we pull the whole list and
    filter locally with accent-insensitive matching. Any ``code`` returned here
    can be passed straight to /tts.
    """
    import requests

    try:
        raw = _fetch_vbee_catalog()
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f"[tts] VBEE voice search failed: {e}")
        raise HTTPException(status_code=502, detail="Không gọi được VBEE để tìm giọng")

    needle = _strip_accents(q)
    voices_list = []
    for v in raw:
        if not isinstance(v, dict) or not v.get("code"):
            continue
        if needle and needle not in _strip_accents(v.get("name") or ""):
            continue
        voices_list.append({
            "code": v.get("code"),
            "name": v.get("name"),
            "gender": v.get("gender"),
            "locale": v.get("locale"),
            "language_code": v.get("language_code"),
            "category": v.get("category"),
        })
        if len(voices_list) >= limit:
            break

    logger.info(f"[tts] VBEE search q={q!r} -> {len(voices_list)} voices")
    return {"voices": voices_list}


@router.post("/prepare")
async def prepare_tts_records(
    request: schemas.TTSRequest,
    db: Session = Depends(get_db)
):
    """
    Prepare audio records for all chapters with IDLE status
    This should be called when entering Step 5
    """
    # Check if story exists
    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Get all chapters
    chapters = db.query(models.Chapter).filter(
        models.Chapter.story_id == request.story_id
    ).order_by(models.Chapter.chapter_number).all()

    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found")

    # Delete old audio records — remove their files from disk first so re-running
    # /prepare doesn't leave orphan chapter_*.mp3 accumulating in storage.
    old_records = db.query(models.AudioFile).filter(
        models.AudioFile.chapter_id.in_([ch.id for ch in chapters])
    ).all()
    for rec in old_records:
        _delete_audio_file(rec.file_path)
    db.query(models.AudioFile).filter(
        models.AudioFile.chapter_id.in_([ch.id for ch in chapters])
    ).delete(synchronize_session=False)

    # Create audio records with IDLE status
    audio_records = []
    for chapter in chapters:
        audio_record = models.AudioFile(
            chapter_id=chapter.id,
            format=request.audio_type if hasattr(request, 'audio_type') else "mp3",
            bitrate=str(request.bitrate) if hasattr(request, 'bitrate') else "128",
            status="idle"
        )
        db.add(audio_record)
        audio_records.append(audio_record)

    db.commit()

    logger.info(f"Prepared {len(audio_records)} audio records for story {request.story_id}")

    return {
        "success": True,
        "story_id": request.story_id,
        "total_records": len(audio_records),
        "message": f"Prepared {len(audio_records)} audio records"
    }

@router.get("/audio-status/{story_id}")
async def get_audio_status(story_id: str, db: Session = Depends(get_db)):
    """
    Get audio processing status for all chapters of a story
    Returns list of audio records with their status
    """
    # Get all chapters with their audio files
    chapters = db.query(models.Chapter).filter(
        models.Chapter.story_id == story_id
    ).order_by(models.Chapter.chapter_number).all()

    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found")

    result = []
    for chapter in chapters:
        # Get audio file for this chapter (should be only one)
        audio = db.query(models.AudioFile).filter(
            models.AudioFile.chapter_id == chapter.id
        ).first()

        result.append({
            "chapter_id": chapter.id,
            "chapter_number": chapter.chapter_number,
            "chapter_title": chapter.title,
            "audio_id": audio.id if audio else None,
            "status": audio.status if audio else "not_created",
            "request_id": audio.request_id if audio else None,
            "audio_link": audio.audio_link if audio else None,
            "file_path": audio.file_path if audio else None,
            "error_message": audio.error_message if audio else None,
            "updated_at": audio.updated_at.isoformat() if audio and audio.updated_at else None
        })

    return {
        "story_id": story_id,
        "total_chapters": len(result),
        "audio_records": result
    }

@router.post("/start-background")
async def start_tts_background(
    request: schemas.TTSRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Start TTS processing in background"""
    # Check if story exists
    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Check if audio records exist
    audio_count = db.query(models.AudioFile).join(models.Chapter).filter(
        models.Chapter.story_id == request.story_id
    ).count()

    if audio_count == 0:
        raise HTTPException(status_code=400, detail="No audio records found. Call /prepare first")

    # Create task
    task = models.Task(
        story_id=request.story_id,
        type="tts",
        status="running"
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Start background processing
    config = _build_tts_config(request)

    background_tasks.add_task(process_tts_task, task.id, story.id, config)

    return {
        "task_id": task.id,
        "status": "started",
        "message": "TTS processing started in background"
    }

@router.post("/start-merged")
async def start_tts_merged(
    request: schemas.TTSRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Start TTS processing for merged content (single audio file)"""
    from app.services.tts_processor import VbeeTTSProcessor

    # Check if story exists
    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Check merged content
    if not story.merged_content or story.merged_content.strip() == "":
        raise HTTPException(status_code=400, detail="No merged content found. Please edit content in Grammar step first.")

    # Create task
    task = models.Task(
        story_id=request.story_id,
        type="tts_merged",
        engine="vbee",
        status="running",
        total_items=1
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Get config
    config = _build_tts_config(request)

    # Start background processing
    from app.workers.tts_worker import process_merged_tts_task
    background_tasks.add_task(process_merged_tts_task, task.id, story.id, config)

    return {
        "task_id": task.id,
        "status": "started",
        "char_count": len(story.merged_content),
        "message": f"TTS processing started for {len(story.merged_content)} characters"
    }


@router.get("/merged-status/{story_id}")
async def get_merged_tts_status(story_id: str, engine: Optional[str] = None, db: Session = Depends(get_db)):
    """Get TTS status for merged content.

    ``engine`` (optional) scopes the result to the caller's currently selected
    TTS engine ('vbee' | 'omnivoice') — a story can carry a leftover
    merged_audio row from whichever engine ran last, and without this filter
    the UI would show a VBEE-produced file while the user is mid-run on
    OmniVoice (or vice versa).
    """
    # Get story
    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Get merged audio
    query = db.query(models.MergedAudio).filter(models.MergedAudio.story_id == story_id)
    if engine:
        query = query.filter(models.MergedAudio.engine == engine)
    merged_audio = query.order_by(models.MergedAudio.created_at.desc()).first()

    # Get latest task
    task_query = db.query(models.Task).filter(
        models.Task.story_id == story_id,
        models.Task.type == "tts_merged"
    )
    if engine:
        task_query = task_query.filter(models.Task.engine == engine)
    task = task_query.order_by(models.Task.created_at.desc()).first()

    return {
        "story_id": story_id,
        "has_merged_content": bool(story.merged_content),
        "char_count": len(story.merged_content) if story.merged_content else 0,
        "task_status": task.status if task else None,
        "task_error": task.error_message if task else None,
        "audio_file": merged_audio.file_path if merged_audio else None,
        "audio_size": merged_audio.file_size if merged_audio else None,
        "audio_format": merged_audio.format if merged_audio else None
    }


# ==================== OmniVoice per-segment TTS ====================

def _seg_out(seg: models.TtsSegment) -> dict:
    return {
        "id": seg.id,
        "seg_index": seg.seg_index,
        "text": seg.text,
        "status": seg.status,
        "error_message": seg.error_message,
        "attempts": seg.attempts or 0,
        "duration": seg.duration,
        "gen_sec": seg.gen_sec,
        "has_audio": bool(seg.file_path),
    }


@router.post("/segments/split")
async def split_segments(request: schemas.SegmentSplitRequest, db: Session = Depends(get_db)):
    """Split a story's merged content into TTS segments (replaces any existing)."""
    from app.services import segment_tts
    from app.workers.tts_worker import is_story_active

    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    if not story.merged_content or not story.merged_content.strip():
        raise HTTPException(status_code=400, detail="No merged content found. Please edit content first.")
    # Never wipe segments while a generation batch is running against them.
    if is_story_active(request.story_id):
        raise HTTPException(status_code=409, detail="Đang chạy TTS — hãy chờ xong trước khi tách lại.")

    config = _build_tts_config(request)
    segs = segment_tts.create_segments(db, story, request.split_mode, config)
    return {
        "story_id": story.id,
        "split_mode": request.split_mode,
        "segments": [_seg_out(s) for s in segs],
        "stats": segment_tts.segment_stats(db, story.id),
    }


@router.get("/segments/{story_id}")
async def list_segments(story_id: str, db: Session = Depends(get_db)):
    """List a story's segments + whether the source story changed since split."""
    from app.services import segment_tts
    from app.workers.tts_worker import is_story_active

    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    segs = db.query(models.TtsSegment).filter(
        models.TtsSegment.story_id == story_id
    ).order_by(models.TtsSegment.seg_index).all()

    return {
        "story_id": story_id,
        "split_mode": segs[0].split_mode if segs else None,
        "source_changed": segment_tts.source_changed(db, story),
        # Authoritative "a generation batch/retry is running" flag — the poller
        # keys off this to stop, since after a cancel some segments stay 'pending'
        # with nothing actually running.
        "running": is_story_active(story_id),
        "segments": [_seg_out(s) for s in segs],
        "stats": segment_tts.segment_stats(db, story_id),
    }


@router.post("/segments/run")
async def run_segments(
    request: schemas.TTSRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Generate audio for all pending/error segments in the background.

    Applies the *current* config from the request to the segments about to be
    generated, so a voice/speed/bitrate change since split time takes effect
    without needing a re-split.
    """
    from app.workers.tts_worker import process_segments_task, try_acquire_story, release_story

    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    todo = db.query(models.TtsSegment).filter(
        models.TtsSegment.story_id == request.story_id,
        models.TtsSegment.status.in_(["pending", "error"]),
    ).count()
    if todo == 0:
        return {"status": "idle", "message": "Tất cả câu đã xong.", "queued": 0}

    if not try_acquire_story(request.story_id):
        return {"status": "busy", "message": "Đang chạy TTS cho truyện này.", "queued": 0}

    try:
        # Refresh config on the segments we're about to generate.
        config = _build_tts_config(request)
        db.query(models.TtsSegment).filter(
            models.TtsSegment.story_id == request.story_id,
            models.TtsSegment.status.in_(["pending", "error"]),
        ).update({models.TtsSegment.config: config}, synchronize_session=False)
        db.commit()
    except Exception:
        release_story(request.story_id)
        raise

    background_tasks.add_task(process_segments_task, request.story_id)
    return {"status": "started", "queued": todo}


@router.post("/segments/cancel")
async def cancel_segments(request: schemas.SegmentMergeRequest, db: Session = Depends(get_db)):
    """Ask the running per-segment generation to stop after the current sentence.

    A single GPU generation can't be interrupted mid-way, so this is a graceful
    stop: the in-flight segment finishes, then no further segments start. Already
    done segments stay done; the rest remain 'pending' so a later run resumes.
    """
    from app.workers.tts_worker import request_cancel

    if request_cancel(request.story_id):
        return {"status": "cancelling",
                "message": "Đang dừng sau khi câu hiện tại sinh xong…"}
    return {"status": "idle", "message": "Không có tiến trình TTS nào đang chạy."}


@router.post("/segments/{segment_id}/retry")
async def retry_segment(
    segment_id: str,
    request: schemas.TTSRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Reset one segment and regenerate it (per-row Re-TTS), using current config."""
    from app.workers.tts_worker import process_single_segment_task, try_acquire_story, release_story

    seg = db.query(models.TtsSegment).filter(models.TtsSegment.id == segment_id).first()
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")

    if not try_acquire_story(seg.story_id):
        return {"status": "busy", "message": "Đang chạy TTS cho truyện này."}

    try:
        _delete_audio_file(seg.file_path)
        seg.file_path = None
        seg.status = "pending"
        seg.error_message = None
        seg.config = _build_tts_config(request)
        db.commit()
    except Exception:
        release_story(seg.story_id)
        raise

    background_tasks.add_task(process_single_segment_task, segment_id)
    return {"status": "started", "segment_id": segment_id, "seg_index": seg.seg_index}


@router.delete("/segments/{segment_id}")
async def delete_segment(segment_id: str, db: Session = Depends(get_db)):
    """Delete one segment (and its file), then reindex the rest."""
    from app.workers.tts_worker import is_story_active

    seg = db.query(models.TtsSegment).filter(models.TtsSegment.id == segment_id).first()
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Don't reindex/delete rows out from under a running generation batch.
    if is_story_active(seg.story_id):
        raise HTTPException(status_code=409, detail="Đang chạy TTS — hãy chờ xong trước khi xóa.")

    story_id = seg.story_id
    _delete_audio_file(seg.file_path)
    db.delete(seg)
    db.commit()

    # Reindex remaining segments so #numbers stay contiguous.
    rest = db.query(models.TtsSegment).filter(
        models.TtsSegment.story_id == story_id
    ).order_by(models.TtsSegment.seg_index).all()
    for i, s in enumerate(rest, start=1):
        if s.seg_index != i:
            s.seg_index = i
    db.commit()

    return {"status": "deleted", "segment_id": segment_id, "remaining": len(rest)}


@router.get("/segments/{segment_id}/audio")
async def segment_audio(segment_id: str, db: Session = Depends(get_db)):
    """Stream one segment's mp3 (Nghe / Tải WAV per row)."""
    seg = db.query(models.TtsSegment).filter(models.TtsSegment.id == segment_id).first()
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")
    if not seg.file_path or not os.path.exists(seg.file_path):
        raise HTTPException(status_code=404, detail="Segment audio not generated yet")
    return FileResponse(seg.file_path, media_type="audio/mpeg",
                        filename=f"segment_{seg.seg_index:04d}.mp3")


@router.post("/segments/merge")
async def merge_segments_endpoint(
    request: schemas.SegmentMergeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Concatenate all done segments into one final mp3 (background).

    Progress/result is reported through the existing GET /merged-status/{story_id}.
    """
    from app.workers.tts_worker import process_segments_merge_task
    from app.services import segment_tts

    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    stats = segment_tts.segment_stats(db, request.story_id)
    if stats["total"] == 0:
        raise HTTPException(status_code=400, detail="Chưa có câu nào để ghép.")
    if not stats["all_done"]:
        raise HTTPException(status_code=400,
                            detail="Còn câu chưa xong — hãy chạy/retry hết trước khi ghép.")

    task = models.Task(story_id=story.id, type="tts_merged", engine="omnivoice", status="running", total_items=1)
    db.add(task)
    db.commit()
    db.refresh(task)

    background_tasks.add_task(process_segments_merge_task, story.id, task.id)
    return {"task_id": task.id, "status": "started", "segment_count": stats["total"]}


@router.post("/retry-chapter/{chapter_id}")
async def retry_chapter_tts(
    chapter_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Retry TTS for a single failed chapter
    This endpoint is used to re-generate audio for a specific chapter
    """
    from app.workers.tts_worker import process_single_chapter_tts

    # Check if chapter exists
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    # Get audio record for this chapter
    audio_record = db.query(models.AudioFile).filter(
        models.AudioFile.chapter_id == chapter_id
    ).first()

    if not audio_record:
        raise HTTPException(status_code=404, detail="Audio record not found for this chapter")

    # Reset audio record status to idle — delete the stale file first so the old
    # mp3 isn't orphaned on disk when file_path is cleared.
    _delete_audio_file(audio_record.file_path)
    audio_record.status = "idle"
    audio_record.error_message = None
    audio_record.request_id = None
    audio_record.audio_link = None
    audio_record.file_path = None
    db.commit()

    # Get TTS config from audio record
    config = {
        "voice_code": "hn_female_ngochuyen_full_48k-fhg",  # Default
        "audio_type": audio_record.format or "mp3",
        "bitrate": int(audio_record.bitrate) if audio_record.bitrate else 128,
        "speed": 1.0
    }

    # Start background processing for this chapter
    background_tasks.add_task(process_single_chapter_tts, chapter_id, config)

    logger.info(f"Retry TTS requested for chapter {chapter_id} (Chapter {chapter.chapter_number})")

    return {
        "success": True,
        "chapter_id": chapter_id,
        "chapter_number": chapter.chapter_number,
        "status": "idle",
        "message": f"Retry started for Chapter {chapter.chapter_number}"
    }
