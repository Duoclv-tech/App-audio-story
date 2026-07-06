from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from loguru import logger

from app.database import get_db
from app import models, schemas
from app.workers.download_worker import download_chapters_task

router = APIRouter()

@router.post("/start", response_model=schemas.DownloadResponse)
async def start_download(
    request: schemas.DownloadRequest,
    db: Session = Depends(get_db)
):
    """Start downloading chapters and wait for completion"""
    try:
        # Check if story exists
        story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        # Create task
        task = models.Task(
            story_id=request.story_id,
            type="download",
            status="running",
            total_items=story.end_chapter - story.start_chapter + 1 if story.end_chapter else None
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # Run download synchronously
        result = await download_chapters_task(
            task.id,
            story.id,
            story.start_chapter,
            story.end_chapter
        )

        if result.get("success"):
            # Update story status and step after successful download
            story.status = "downloaded"
            story.current_step = 3  # Move to Edit step
            db.commit()

            return {
                "task_id": task.id,
                "status": "completed",
                "message": f"Downloaded {result.get('successful', 0)} chapters successfully",
                "total": result.get("total", 0),
                "successful": result.get("successful", 0),
                "failed": result.get("failed", 0)
            }
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Download failed"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting download: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{task_id}/status", response_model=schemas.TaskResponse)
async def get_download_status(task_id: str, db: Session = Depends(get_db)):
    """Get download task status"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.post("/pause")
async def pause_download(task_id: str, db: Session = Depends(get_db)):
    """Pause download"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "paused"
    db.commit()
    return {"message": "Download paused"}

@router.post("/resume")
async def resume_download(task_id: str, db: Session = Depends(get_db)):
    """Resume download"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "running"
    db.commit()
    return {"message": "Download resumed"}

@router.post("/cancel")
async def cancel_download(task_id: str, db: Session = Depends(get_db)):
    """Cancel download"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "cancelled"
    db.commit()
    return {"message": "Download cancelled"}
