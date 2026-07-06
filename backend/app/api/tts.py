from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from loguru import logger
from typing import List

from app.database import get_db
from app import models, schemas
from app.workers.tts_worker import process_tts_task

router = APIRouter()

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
    config = {
        "voice_code": request.voice_code if hasattr(request, 'voice_code') else "hn_female_ngochuyen_full_48k-fhg",
        "audio_type": request.audio_type if hasattr(request, 'audio_type') else "mp3",
        "bitrate": request.bitrate if hasattr(request, 'bitrate') else 128,
        "speed": request.speed if hasattr(request, 'speed') else 1.0
    }

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
    voices = db.query(models.Voice).filter(
        models.Voice.is_active == True
    ).order_by(models.Voice.rank).all()

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

@router.post("/pause")
async def pause_tts(task_id: str, db: Session = Depends(get_db)):
    """Pause TTS"""
    # TODO: Implement pause logic
    return {"message": "TTS paused"}

@router.post("/resume")
async def resume_tts(task_id: str, db: Session = Depends(get_db)):
    """Resume TTS"""
    # TODO: Implement resume logic
    return {"message": "TTS resumed"}

@router.post("/cancel")
async def cancel_tts(task_id: str, db: Session = Depends(get_db)):
    """Cancel TTS"""
    # TODO: Implement cancel logic
    return {"message": "TTS cancelled"}

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

    # Delete old audio records if any
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
    config = {
        "voice_code": request.voice_code if hasattr(request, 'voice_code') else "hn_female_ngochuyen_full_48k-fhg",
        "audio_type": request.audio_type if hasattr(request, 'audio_type') else "mp3",
        "bitrate": request.bitrate if hasattr(request, 'bitrate') else 128,
        "speed": request.speed if hasattr(request, 'speed') else 1.0
    }

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
        status="running",
        total_items=1
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Get config
    config = {
        "voice_code": request.voice_code if hasattr(request, 'voice_code') else "hn_female_ngochuyen_full_48k-fhg",
        "audio_type": request.audio_type if hasattr(request, 'audio_type') else "mp3",
        "bitrate": request.bitrate if hasattr(request, 'bitrate') else 128,
        "speed": request.speed if hasattr(request, 'speed') else 1.0
    }

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
async def get_merged_tts_status(story_id: str, db: Session = Depends(get_db)):
    """Get TTS status for merged content"""
    # Get story
    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Get merged audio
    merged_audio = db.query(models.MergedAudio).filter(
        models.MergedAudio.story_id == story_id
    ).first()

    # Get latest task
    task = db.query(models.Task).filter(
        models.Task.story_id == story_id,
        models.Task.type == "tts_merged"
    ).order_by(models.Task.created_at.desc()).first()

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

    # Reset audio record status to idle
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
