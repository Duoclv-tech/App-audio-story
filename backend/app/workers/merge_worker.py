"""
Audio Merge Worker
Background task worker for merging audio files
"""
import asyncio
from typing import Dict, Optional
from loguru import logger

from app.database import SessionLocal
from app.services.audio_merger import AudioMerger
from app.services.output_delivery import deliver_final, safe_file_stem
from app import models


async def merge_audio_task(
    task_id: str,
    story_id: str,
    config: Optional[Dict] = None
):
    """
    Background task to merge audio files for a story

    Args:
        task_id: Task ID for progress tracking
        story_id: Story ID
        config: Merge configuration (format, bitrate, crossfade, etc.)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting audio merge task {task_id} for story {story_id}")

        # Default config
        if config is None:
            config = {}

        format = config.get("format", "mp3")
        bitrate = config.get("bitrate", "192k")
        crossfade = config.get("crossfade", 0)

        # Get story from database
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise ValueError(f"Story {story_id} not found")

        # Update task status
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task:
            task.status = "running"
            db.commit()

        # Create audio merger
        merger = AudioMerger()

        # Check FFmpeg availability
        if not merger.ffmpeg_available:
            raise RuntimeError("FFmpeg is not installed. Please install FFmpeg to use audio merging.")

        # Merge audio files
        result = await merger.merge_story_audio(
            story_id=story_id,
            task_id=task_id,
            db=db,
            format=format,
            bitrate=bitrate,
            crossfade=crossfade
        )

        if result.get("success"):
            logger.info(f"Audio merge task {task_id} completed successfully")
            logger.info(f"Output file: {result['output_path']}")
            logger.info(f"Duration: {result['duration']} seconds")
            logger.info(f"File size: {result['file_size']} bytes")
        else:
            logger.error(f"Audio merge task {task_id} failed: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error in audio merge task {task_id}: {e}")

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


async def merge_selected_chapters(
    story_id: str,
    chapter_ids: list,
    output_name: str,
    config: Optional[Dict] = None
):
    """
    Merge audio files for selected chapters only

    Args:
        story_id: Story ID
        chapter_ids: List of chapter IDs to merge
        output_name: Custom output file name
        config: Merge configuration
    """
    db = SessionLocal()

    try:
        # Default config
        if config is None:
            config = {}

        format = config.get("format", "mp3")
        bitrate = config.get("bitrate", "192k")
        crossfade = config.get("crossfade", 0)

        # Get audio files for selected chapters
        audio_files = db.query(models.AudioFile).filter(
            models.AudioFile.chapter_id.in_(chapter_ids)
        ).join(
            models.Chapter
        ).order_by(
            models.Chapter.chapter_number
        ).all()

        if not audio_files:
            return {
                "success": False,
                "error": "No audio files found for selected chapters"
            }

        # Get file paths
        input_paths = [af.file_path for af in audio_files]

        # Create merger
        merger = AudioMerger()

        # Check FFmpeg
        if not merger.ffmpeg_available:
            return {
                "success": False,
                "error": "FFmpeg not installed"
            }

        # Define output path
        from pathlib import Path
        from app.config import settings

        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        story_folder = story.title.replace(' ', '_') if story else "unknown"
        output_dir = Path(settings.STORAGE_PATH) / "merged" / story_folder
        output_path = output_dir / f"{output_name}.{format}"

        # Merge files
        result = await merger.merge_audio_files(
            input_files=input_paths,
            output_path=str(output_path),
            format=format,
            bitrate=bitrate,
            crossfade=crossfade
        )

        if result.get("success"):
            # Deliver finished audio to the user's output folder (Downloads default)
            _name = safe_file_stem(story.title if story and story.title else story_id, output_name)
            final_path = deliver_final(str(output_path), db, filename=f"{_name}.{format}")
            result["output_path"] = final_path

            # Save merged audio record
            merged_audio = models.MergedAudio(
                story_id=story_id,
                file_path=final_path,
                duration=result.get("duration", 0),
                format=format,
                # Note: bitrate, source_count and custom_name fields not in MergedAudio model
                # bitrate=bitrate,
                # source_count=len(input_paths),
                # custom_name=output_name,
                total_chapters=len(input_paths),
                file_size=result.get("file_size", 0)
            )
            db.add(merged_audio)
            db.commit()

        return result

    except Exception as e:
        logger.error(f"Error merging selected chapters: {e}")
        return {
            "success": False,
            "error": str(e)
        }

    finally:
        db.close()


def run_merge_task(task_id: str, story_id: str, config: Optional[Dict] = None):
    """
    Synchronous wrapper for running merge task
    Can be used with threading or multiprocessing

    Args:
        task_id: Task ID
        story_id: Story ID
        config: Merge configuration
    """
    # Create new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # Run the async task
        result = loop.run_until_complete(
            merge_audio_task(task_id, story_id, config)
        )
        return result
    finally:
        loop.close()


async def check_and_resume_merge_tasks():
    """
    Check for interrupted merge tasks and resume them
    This can be called on startup to resume any pending merge operations
    """
    db = SessionLocal()

    try:
        # Find all pending or running merge tasks
        pending_tasks = db.query(models.Task).filter(
            models.Task.type == "merge",
            models.Task.status.in_(["queued", "running", "paused"])
        ).all()

        for task in pending_tasks:
            logger.info(f"Resuming merge task {task.id} for story {task.story_id}")

            # Resume merge
            await merge_audio_task(
                task_id=task.id,
                story_id=task.story_id,
                config=task.config if hasattr(task, 'config') else None
            )

        logger.info(f"Resumed {len(pending_tasks)} merge tasks")

    except Exception as e:
        logger.error(f"Error checking/resuming merge tasks: {e}")

    finally:
        db.close()


async def validate_audio_files_before_merge(story_id: str) -> Dict:
    """
    Validate that all audio files exist before attempting merge

    Args:
        story_id: Story ID

    Returns:
        Validation result dictionary
    """
    db = SessionLocal()

    try:
        # Get all audio files for story
        audio_files = db.query(models.AudioFile).join(
            models.Chapter
        ).filter(
            models.Chapter.story_id == story_id
        ).all()

        if not audio_files:
            return {
                "valid": False,
                "error": "No audio files found for story"
            }

        # Get file paths
        file_paths = [af.file_path for af in audio_files]

        # Create merger and validate
        merger = AudioMerger()
        validation_result = merger.validate_audio_files(file_paths)

        return validation_result

    except Exception as e:
        logger.error(f"Error validating audio files: {e}")
        return {
            "valid": False,
            "error": str(e)
        }

    finally:
        db.close()