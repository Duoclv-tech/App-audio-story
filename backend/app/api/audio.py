from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from loguru import logger

from app.database import get_db
from app import models, schemas
from app.workers.merge_worker import merge_audio_task

router = APIRouter()

@router.get("/{story_id}", response_model=List[schemas.AudioFileResponse])
async def list_audio_files(story_id: str, db: Session = Depends(get_db)):
    """List all audio files of a story"""
    # TODO: Implement list logic
    return []

@router.post("/merge/start", response_model=schemas.AudioMergeResponse)
async def start_audio_merge(
    request: schemas.AudioMergeRequest,
    db: Session = Depends(get_db)
):
    """Start merging audio files and wait for completion"""
    # Check if story exists
    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Create task
    task = models.Task(
        story_id=request.story_id,
        type="merge",
        status="running"
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Run merge synchronously
    config = {
        "format": request.format if hasattr(request, 'format') else "mp3",
        "bitrate": request.bitrate if hasattr(request, 'bitrate') else "192k",
        "crossfade": request.crossfade if hasattr(request, 'crossfade') else 0
    }

    result = await merge_audio_task(task.id, story.id, config)

    if result.get("success"):
        # Update story status and step after successful merge
        story.status = "audio_merged"
        story.current_step = 7  # Move to Video step
        db.commit()

        return {
            "task_id": task.id,
            "status": "completed",
            "message": f"Audio merge completed. File: {result.get('output_path', '')}"
        }
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "Audio merge failed"))

@router.get("/merge/{task_id}/status", response_model=schemas.TaskResponse)
async def get_merge_status(task_id: str, db: Session = Depends(get_db)):
    """Get merge task status"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
