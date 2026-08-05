"""
TTS Worker
Background task worker for text-to-speech processing
"""
import asyncio
import threading
from typing import Dict, Optional
from loguru import logger

from app.database import SessionLocal
from app.services.tts_processor import VbeeTTSProcessor
from app import models
from app.config import settings


def _engine(config: Optional[Dict]) -> str:
    """Which TTS engine to use: 'vbee' (default, cloud) or 'ai_voice_local' (local)."""
    return ((config or {}).get("engine") or "vbee").lower()


# ---- Per-story segment-generation lock (single desktop process) -------------
# Serialises segment generation per story so overlapping run/run, run/retry and
# retry/retry requests can't double-generate the same segment. The GPU model
# lock already serialises the actual generate() call, but that doesn't stop two
# tasks from each iterating the same pending rows; this does. Endpoints acquire
# synchronously (closing the schedule-time race) and the task releases when done.
_active_stories: set = set()
# Stories the user asked to stop. Checked before each segment in the run loop, so
# "cancel" stops after the current sentence finishes (a single GPU generation is
# blocking and can't be interrupted mid-way). Remaining segments stay 'pending'
# so a later run resumes from where it left off.
_cancel_stories: set = set()
_active_lock = threading.Lock()


def try_acquire_story(story_id: str) -> bool:
    """Reserve a story for generation. Returns False if one is already active."""
    with _active_lock:
        if story_id in _active_stories:
            return False
        _active_stories.add(story_id)
        _cancel_stories.discard(story_id)  # clear any stale cancel from a prior run
        return True


def release_story(story_id: str) -> None:
    with _active_lock:
        _active_stories.discard(story_id)
        _cancel_stories.discard(story_id)


def is_story_active(story_id: str) -> bool:
    with _active_lock:
        return story_id in _active_stories


def any_story_active() -> bool:
    """True if any AI Voice local segment generation is running (GPU busy) — used by
    the quick-build guard to avoid starting a batch on top of a wizard TTS run."""
    with _active_lock:
        return len(_active_stories) > 0


def request_cancel(story_id: str) -> bool:
    """Ask a running generation to stop after its current segment.

    Returns False if no generation is active for this story (nothing to cancel).
    """
    with _active_lock:
        if story_id not in _active_stories:
            return False
        _cancel_stories.add(story_id)
        return True


def is_cancel_requested(story_id: str) -> bool:
    with _active_lock:
        return story_id in _cancel_stories


def process_segments_task(story_id: str) -> Dict:
    """Generate audio for every pending/error segment of a story, one at a time.

    Runs in a FastAPI BackgroundTask (own DB session). Each segment's status is
    committed as it finishes so the frontend sees live progress by polling. The
    AI Voice local GPU model lock already serialises generation, so we process
    sequentially rather than fanning out.
    """
    from app.services import segment_tts

    db = SessionLocal()
    try:
        pending = db.query(models.TtsSegment).filter(
            models.TtsSegment.story_id == story_id,
            models.TtsSegment.status.in_(["pending", "error"]),
        ).order_by(models.TtsSegment.seg_index).all()

        logger.info(f"[segment-tts] story {story_id}: running {len(pending)} segment(s)")
        ok = 0
        processed = 0
        for seg in pending:
            # Stop before starting the next sentence if the user hit cancel. The
            # already-generated ones keep their 'done' status; the rest remain
            # 'pending' so a later run picks up where this stopped.
            if is_cancel_requested(story_id):
                logger.info(f"[segment-tts] story {story_id}: cancelled after {processed}/{len(pending)}")
                return {"success": True, "processed": processed, "ok": ok, "cancelled": True}
            result = segment_tts.synthesize_segment(db, seg)
            processed += 1
            if result.get("success"):
                ok += 1
        logger.info(f"[segment-tts] story {story_id}: done, {ok}/{len(pending)} succeeded")
        return {"success": True, "processed": processed, "ok": ok}
    except Exception as e:  # noqa: BLE001
        logger.error(f"[segment-tts] batch failed for story {story_id}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        release_story(story_id)
        db.close()


def process_single_segment_task(segment_id: str) -> Dict:
    """(Re)generate one segment — used by the per-row Re-TTS button."""
    from app.services import segment_tts

    db = SessionLocal()
    story_id = None
    try:
        seg = db.query(models.TtsSegment).filter(
            models.TtsSegment.id == segment_id
        ).first()
        if not seg:
            return {"success": False, "error": "Segment not found"}
        story_id = seg.story_id
        return segment_tts.synthesize_segment(db, seg)
    finally:
        if story_id:
            release_story(story_id)
        db.close()


def process_segments_merge_task(story_id: str, task_id: str) -> Dict:
    """Concatenate a story's done segments into one final mp3, tracked by a Task
    row so the existing merged-status polling endpoint reports progress."""
    from app.services import segment_tts

    db = SessionLocal()
    try:
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            if task:
                task.status = "failed"
                task.error_message = "Story not found"
                db.commit()
            return {"success": False, "error": "Story not found"}

        result = segment_tts.merge_segments(db, story)
        if task:
            if result.get("success"):
                task.status = "completed"
                task.completed_items = 1
                task.progress = 100
            else:
                task.status = "failed"
                task.error_message = result.get("error", "Unknown error")
            db.commit()
        return result
    except Exception as e:  # noqa: BLE001
        logger.error(f"[segment-tts] merge failed for story {story_id}: {e}")
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(e)
            db.commit()
        return {"success": False, "error": str(e)}
    finally:
        release_story(story_id)
        db.close()


def resume_stuck_segments() -> None:
    """Reset segments left 'processing' by a crashed/closed app back to 'pending'.

    Called on startup — the in-memory background task that was generating them is
    gone, so the row would otherwise be stuck spinning forever.
    """
    db = SessionLocal()
    try:
        stuck = db.query(models.TtsSegment).filter(
            models.TtsSegment.status == "processing"
        ).all()
        for seg in stuck:
            seg.status = "pending"
        if stuck:
            db.commit()
            logger.info(f"[segment-tts] reset {len(stuck)} stuck 'processing' segment(s) to pending")
    except Exception as e:  # noqa: BLE001
        logger.error(f"[segment-tts] resume_stuck_segments failed: {e}")
    finally:
        db.close()


async def process_tts_task(
    task_id: str,
    story_id: str,
    config: Optional[Dict] = None
):
    """
    Background task to process TTS for all chapters

    Args:
        task_id: Task ID for progress tracking
        story_id: Story ID to process
        config: TTS configuration (voice, speed, bitrate, etc.)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting TTS task {task_id} for story {story_id}")

        # Default config
        if config is None:
            config = {}

        voice_code = config.get("voice_code", "hn_female_ngochuyen_full_48k-fhg")
        audio_type = config.get("audio_type", "mp3")
        bitrate = config.get("bitrate", 128)
        speed = config.get("speed", 1.0)

        # Get story from database
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise ValueError(f"Story {story_id} not found")

        # Update task status
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task:
            task.status = "running"
            db.commit()

        # Process all chapters via the selected engine
        if _engine(config) == "ai_voice_local":
            from app.services.ai_voice_local_processor import AiVoiceLocalProcessor
            result = await AiVoiceLocalProcessor(db=db).process_story(
                story_id=story_id, task_id=task_id, db=db, config=config
            )
        else:
            tts_processor = VbeeTTSProcessor(db=db)
            result = await tts_processor.process_story(
                story_id=story_id,
                task_id=task_id,
                db=db,
                voice_code=voice_code,
                audio_type=audio_type,
                bitrate=bitrate,
                speed=speed,
                max_concurrent=2  # Limit concurrent TTS requests
            )

        if result.get("success"):
            logger.info(f"TTS task {task_id} completed: {result['successful']} successful, {result['failed']} failed")
        else:
            logger.error(f"TTS task {task_id} failed: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error in TTS task {task_id}: {e}")

        # Update task with error
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(e)
            db.commit()

        return {
            "success": False,
            "error": str(e)
        }

    finally:
        db.close()


async def process_single_chapter_tts(
    chapter_id: str,
    config: Optional[Dict] = None
):
    """
    Process TTS for a single chapter

    Args:
        chapter_id: Chapter ID to process
        config: TTS configuration
    """
    db = SessionLocal()

    try:
        # Default config
        if config is None:
            config = {}

        voice_code = config.get("voice_code", "hn_female_ngochuyen_full_48k-fhg")
        audio_type = config.get("audio_type", "mp3")
        bitrate = config.get("bitrate", 128)
        speed = config.get("speed", 1.0)

        # Process chapter via the selected engine
        if _engine(config) == "ai_voice_local":
            from app.services.ai_voice_local_processor import AiVoiceLocalProcessor
            result = await AiVoiceLocalProcessor(db=db).process_chapter(
                chapter_id=chapter_id, db=db, config=config
            )
        else:
            tts_processor = VbeeTTSProcessor(db=db)
            result = await tts_processor.process_chapter(
                chapter_id=chapter_id,
                db=db,
                voice_code=voice_code,
                audio_type=audio_type,
                bitrate=bitrate,
                speed=speed
            )

        if result.get("success"):
            logger.info(f"TTS processing completed for chapter {chapter_id}")
        else:
            logger.error(f"TTS processing failed for chapter {chapter_id}: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error processing TTS for chapter {chapter_id}: {e}")
        return {
            "success": False,
            "error": str(e)
        }

    finally:
        db.close()


async def process_merged_tts_task(
    task_id: str,
    story_id: str,
    config: Optional[Dict] = None
):
    """
    Background task to process TTS for merged content (single audio file)

    Args:
        task_id: Task ID for progress tracking
        story_id: Story ID to process
        config: TTS configuration (voice, speed, bitrate, etc.)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting merged TTS task {task_id} for story {story_id}")

        # Default config
        if config is None:
            config = {}

        voice_code = config.get("voice_code", "hn_female_ngochuyen_full_48k-fhg")
        audio_type = config.get("audio_type", "mp3")
        bitrate = config.get("bitrate", 128)
        speed = config.get("speed", 1.0)

        # Update task status
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task:
            task.status = "running"
            db.commit()

        # Route to the selected engine
        if _engine(config) == "ai_voice_local":
            from app.services.ai_voice_local_processor import AiVoiceLocalProcessor
            result = await AiVoiceLocalProcessor(db=db).process_merged_content(
                story_id=story_id, db=db, config=config
            )
        else:
            tts_processor = VbeeTTSProcessor(db=db)
            result = await tts_processor.process_merged_content(
                story_id=story_id,
                db=db,
                voice_code=voice_code,
                audio_type=audio_type,
                bitrate=bitrate,
                speed=speed
            )

        # Update task status
        if task:
            if result.get("success"):
                task.status = "completed"
                task.completed_items = 1
                task.progress = 100
                logger.info(f"Merged TTS task {task_id} completed successfully")
            else:
                task.status = "failed"
                task.error_message = result.get("error", "Unknown error")
                logger.error(f"Merged TTS task {task_id} failed: {result.get('error')}")
            db.commit()

        return result

    except Exception as e:
        logger.error(f"Error in merged TTS task {task_id}: {e}")

        # Update task with error
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(e)
            db.commit()

        return {
            "success": False,
            "error": str(e)
        }

    finally:
        db.close()


def run_tts_task(task_id: str, story_id: str, config: Optional[Dict] = None):
    """
    Synchronous wrapper for running TTS task
    Can be used with threading or multiprocessing

    Args:
        task_id: Task ID
        story_id: Story ID
        config: TTS configuration
    """
    # Create new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # Run the async task
        result = loop.run_until_complete(
            process_tts_task(task_id, story_id, config)
        )
        return result
    finally:
        loop.close()


async def check_and_resume_tts_tasks():
    """
    Check for interrupted TTS tasks and resume them
    This can be called on startup to resume any pending TTS processing
    """
    db = SessionLocal()

    try:
        # Find all pending or running TTS tasks
        pending_tasks = db.query(models.Task).filter(
            models.Task.type == "tts",
            models.Task.status.in_(["queued", "running", "paused"])
        ).all()

        for task in pending_tasks:
            logger.info(f"Resuming TTS task {task.id} for story {task.story_id}")

            # Resume TTS processing
            await process_tts_task(
                task_id=task.id,
                story_id=task.story_id,
                config=task.config if hasattr(task, 'config') else None
            )

        logger.info(f"Resumed {len(pending_tasks)} TTS tasks")

    except Exception as e:
        logger.error(f"Error checking/resuming TTS tasks: {e}")

    finally:
        db.close()


async def validate_tts_credentials():
    """
    Validate VBEE TTS credentials (app_id + bearer_token)

    Returns:
        True if credentials are valid, False otherwise
    """
    db = SessionLocal()
    try:
        # Create processor loading credentials from DB first, then .env fallback
        processor = VbeeTTSProcessor(db=db)

        # Check if credentials are configured (resolved from DB or .env)
        if not processor.app_id:
            logger.warning("VBEE_APP_ID not configured")
            return False

        if not processor.bearer_token:
            logger.warning("VBEE_BEARER_TOKEN not configured")
            return False

        # Test with small text
        result = await processor.text_to_speech(
            text="Test",
            voice_code="hn_female_ngochuyen_full_48k-fhg"
        )

        if result:
            logger.info("VBEE credentials validated successfully")
            return True
        else:
            logger.error("VBEE credentials validation failed")
            return False

    except Exception as e:
        logger.error(f"Error validating TTS credentials: {e}")
        return False

    finally:
        db.close()