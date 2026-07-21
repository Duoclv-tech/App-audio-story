"""
TTS Worker
Background task worker for text-to-speech processing
"""
import asyncio
from typing import Dict, Optional
from loguru import logger

from app.database import SessionLocal
from app.services.tts_processor import VbeeTTSProcessor
from app import models
from app.config import settings


def _engine(config: Optional[Dict]) -> str:
    """Which TTS engine to use: 'vbee' (default, cloud) or 'omnivoice' (local)."""
    return ((config or {}).get("engine") or "vbee").lower()


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
        if _engine(config) == "omnivoice":
            from app.services.omnivoice_processor import OmniVoiceProcessor
            result = await OmniVoiceProcessor(db=db).process_story(
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
        if _engine(config) == "omnivoice":
            from app.services.omnivoice_processor import OmniVoiceProcessor
            result = await OmniVoiceProcessor(db=db).process_chapter(
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
        if _engine(config) == "omnivoice":
            from app.services.omnivoice_processor import OmniVoiceProcessor
            result = await OmniVoiceProcessor(db=db).process_merged_content(
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