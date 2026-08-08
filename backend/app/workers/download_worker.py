"""
Download Worker
Background task worker for downloading story chapters
"""
import asyncio
from typing import Optional
from loguru import logger

from app.database import SessionLocal
from app.services.downloader import StoryDownloader
from app import models


async def download_chapters_task(
    task_id: str,
    story_id: str,
    start_chapter: int,
    end_chapter: int
):
    """
    Background task to download chapters

    Args:
        task_id: Task ID for progress tracking
        story_id: Story ID
        start_chapter: Starting chapter number
        end_chapter: Ending chapter number
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting download task {task_id} for story {story_id}")

        # Get story from database
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise ValueError(f"Story {story_id} not found")

        # Check if using custom chapter URLs
        custom_urls = story.custom_chapter_urls if story.custom_chapter_urls else None
        use_custom_urls = custom_urls and len(custom_urls) > 0

        # Update task status
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task:
            task.status = "running"
            # Total items depends on custom URLs or chapter range
            task.total_items = len(custom_urls) if use_custom_urls else (end_chapter - start_chapter + 1)
            task.completed_items = 0
            db.commit()

        # Create downloader instance
        downloader = StoryDownloader(story.url)

        # Download chapters
        results = await downloader.download_chapters_range(
            start=start_chapter,
            end=end_chapter,
            story_id=story_id,
            db=db,
            task_id=task_id,
            max_concurrent=3,  # Limit concurrent downloads
            custom_chapter_urls=custom_urls
        )

        # Count results
        successful = sum(1 for r in results if r.get("success"))
        failed = len(results) - successful

        # Update story statistics
        story.total_chapters = end_chapter - start_chapter + 1
        # Note: chapters_downloaded field may not exist in Story model
        # story.chapters_downloaded = successful

        # Update task final status
        if task:
            if failed == 0:
                task.status = "completed"
                task.progress = 100
                logger.info(f"Download task {task_id} completed successfully")
            else:
                task.status = "completed_with_errors"
                task.error_message = f"{failed} chapters failed to download"
                logger.warning(f"Download task {task_id} completed with {failed} errors")

        db.commit()

        return {
            "success": successful > 0,
            "total": len(results),
            "successful": successful,
            "failed": failed,
            "error": "No chapters downloaded successfully" if successful == 0 else None
        }

    except Exception as e:
        logger.error(f"Error in download task {task_id}: {e}")

        # Update task with error. Roll back first: the exception may have come
        # from db.commit() itself (e.g. SQLite lock timeout), leaving the session
        # in a PendingRollbackError state that would poison the query/commit below
        # and leave the task stuck "running" forever.
        try:
            db.rollback()
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                task.status = "failed"
                task.error_message = str(e)
                db.commit()
        except Exception:
            db.rollback()

        return {
            "success": False,
            "error": str(e)
        }

    finally:
        db.close()


def run_download_task(task_id: str, story_id: str, start_chapter: int, end_chapter: int):
    """
    Synchronous wrapper for running download task
    Can be used with threading or multiprocessing

    Args:
        task_id: Task ID
        story_id: Story ID
        start_chapter: Starting chapter
        end_chapter: Ending chapter
    """
    # Create new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # Run the async task
        result = loop.run_until_complete(
            download_chapters_task(task_id, story_id, start_chapter, end_chapter)
        )
        return result
    finally:
        loop.close()


async def check_and_resume_downloads():
    """
    Check for interrupted download tasks and resume them
    This can be called on startup to resume any pending downloads
    """
    db = SessionLocal()

    try:
        # Find all pending or running download tasks
        pending_tasks = db.query(models.Task).filter(
            models.Task.type == "download",
            models.Task.status.in_(["queued", "running", "paused"])
        ).all()

        for task in pending_tasks:
            # Get story info
            story = db.query(models.Story).filter(
                models.Story.id == task.story_id
            ).first()

            if story:
                logger.info(f"Resuming download task {task.id} for story {story.id}")

                # Resume download
                await download_chapters_task(
                    task_id=task.id,
                    story_id=story.id,
                    start_chapter=story.start_chapter,
                    end_chapter=story.end_chapter
                )

        logger.info(f"Resumed {len(pending_tasks)} download tasks")

    except Exception as e:
        logger.error(f"Error checking/resuming downloads: {e}")

    finally:
        db.close()
