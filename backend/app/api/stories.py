from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from loguru import logger
from datetime import datetime

from app.database import get_db
from app import models, schemas

router = APIRouter()

@router.post("/", response_model=schemas.StoryResponse)
async def create_story(story: schemas.StoryCreate, db: Session = Depends(get_db)):
    """Create a new story project"""
    try:
        logger.info(f"Creating story: {story.title}")

        # Check for duplicate story (same URL + chapter range)
        if story.url:  # Only check if URL is provided
            existing_story = db.query(models.Story).filter(
                models.Story.url == story.url,
                models.Story.start_chapter == story.start_chapter,
                models.Story.end_chapter == story.end_chapter
            ).first()

            if existing_story:
                logger.warning(f"Duplicate story found: {existing_story.id}")
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Story already exists with same URL and chapter range",
                        "existing_story_id": existing_story.id,
                        "existing_story_title": existing_story.title
                    }
                )

        # Create story
        db_story = models.Story(
            title=story.title,
            url=story.url,
            author=story.author,
            total_chapters=story.total_chapters,
            start_chapter=story.start_chapter,
            end_chapter=story.end_chapter,
            custom_chapter_urls=story.custom_chapter_urls,
            status='created'
        )

        db.add(db_story)
        db.commit()
        db.refresh(db_story)

        logger.info(f"Story created successfully: {db_story.id}")
        return db_story

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating story: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create-process", response_model=schemas.StoryResponse)
async def create_process(db: Session = Depends(get_db)):
    """Create a new processing session (story draft)"""
    try:
        logger.info("Creating new processing session")

        # Generate unique title with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_title = f"Story {timestamp}"

        # Create draft story with minimal fields
        db_story = models.Story(
            title=default_title,
            url="",
            start_chapter=1,
            end_chapter=10,
            status='draft'
        )

        db.add(db_story)
        db.commit()
        db.refresh(db_story)

        logger.info(f"Process created successfully: {db_story.id}")
        return db_story

    except Exception as e:
        logger.error(f"Error creating process: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[schemas.StoryResponse])
async def list_stories(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all stories"""
    try:
        stories = db.query(models.Story).order_by(
            models.Story.updated_at.desc()
        ).offset(skip).limit(limit).all()
        return stories
    except Exception as e:
        logger.error(f"Error listing stories: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/with-stats", response_model=schemas.PaginatedStoriesResponse)
async def list_stories_with_stats(
    page: int = 1,
    page_size: int = 20,
    favorite_only: bool = False,
    db: Session = Depends(get_db)
):
    """List all stories with statistics (paginated)"""
    try:
        # Calculate skip value
        skip = (page - 1) * page_size

        # Build query with optional favorite filter
        query = db.query(models.Story)
        if favorite_only:
            query = query.filter(models.Story.is_favorite == True)

        # Get total count
        total = query.count()

        # Get paginated stories
        stories = query.order_by(
            models.Story.updated_at.desc()
        ).offset(skip).limit(page_size).all()

        result = []
        for story in stories:
            # Count chapters
            total_downloaded = db.query(models.Chapter).filter(
                models.Chapter.story_id == story.id
            ).count()

            # Count audio files
            total_audio_generated = db.query(models.AudioFile).join(
                models.Chapter
            ).filter(
                models.Chapter.story_id == story.id,
                models.AudioFile.status == 'success'
            ).count()

            # Check merged audio
            has_merged_audio = db.query(models.MergedAudio).filter(
                models.MergedAudio.story_id == story.id
            ).first() is not None

            result.append({
                **story.__dict__,
                'total_downloaded': total_downloaded,
                'total_audio_generated': total_audio_generated,
                'has_merged_audio': has_merged_audio
            })

        # Calculate total pages
        total_pages = (total + page_size - 1) // page_size

        return {
            'data': result,
            'meta': {
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages
            }
        }
    except Exception as e:
        logger.error(f"Error listing stories with stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/overview", response_model=schemas.StoryOverviewResponse)
async def get_stories_overview(db: Session = Depends(get_db)):
    """Aggregate stats for the home dashboard (fast, single-pass counts)."""
    try:
        total_projects = db.query(models.Story).count()

        total_audio_generated = db.query(models.AudioFile).filter(
            models.AudioFile.status == 'success'
        ).count()

        running_count = db.query(models.Story).filter(
            models.Story.status.in_(['downloading', 'tts_processing'])
        ).count()

        return {
            'total_projects': total_projects,
            'total_audio_generated': total_audio_generated,
            'running_count': running_count,
        }
    except Exception as e:
        logger.error(f"Error building stories overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{story_id}", response_model=schemas.StoryResponse)
async def get_story(story_id: str, db: Session = Depends(get_db)):
    """Get story by ID"""
    try:
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")
        return story
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting story: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{story_id}", response_model=schemas.StoryResponse)
async def update_story(story_id: str, story_update: schemas.StoryUpdate, db: Session = Depends(get_db)):
    """Update story"""
    try:
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        # Check for duplicate if URL or chapter range is being updated
        new_url = story_update.url if story_update.url is not None else story.url
        new_start = story_update.start_chapter if story_update.start_chapter is not None else story.start_chapter
        new_end = story_update.end_chapter if story_update.end_chapter is not None else story.end_chapter

        # Only check if URL is not empty and at least one field changed
        if new_url and (story_update.url is not None or story_update.start_chapter is not None or story_update.end_chapter is not None):
            existing_story = db.query(models.Story).filter(
                models.Story.id != story_id,  # Exclude current story
                models.Story.url == new_url,
                models.Story.start_chapter == new_start,
                models.Story.end_chapter == new_end
            ).first()

            if existing_story:
                logger.warning(f"Duplicate story found during update: {existing_story.id}")
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Another story already exists with same URL and chapter range",
                        "existing_story_id": existing_story.id,
                        "existing_story_title": existing_story.title
                    }
                )

        # Update fields
        if story_update.title is not None:
            story.title = story_update.title
        if story_update.url is not None:
            story.url = story_update.url
        if story_update.author is not None:
            story.author = story_update.author
        if story_update.start_chapter is not None:
            story.start_chapter = story_update.start_chapter
        if story_update.end_chapter is not None:
            story.end_chapter = story_update.end_chapter
        if story_update.custom_chapter_urls is not None:
            story.custom_chapter_urls = story_update.custom_chapter_urls
        if story_update.status is not None:
            story.status = story_update.status
        if story_update.current_step is not None:
            story.current_step = story_update.current_step
        if story_update.tts_config is not None:
            story.tts_config = story_update.tts_config

        db.commit()
        db.refresh(story)
        return story

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating story: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{story_id}")
async def delete_story(story_id: str, db: Session = Depends(get_db)):
    """Delete story"""
    try:
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        db.delete(story)
        db.commit()
        return {"message": "Story deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting story: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{story_id}/toggle-favorite", response_model=schemas.StoryResponse)
async def toggle_favorite(story_id: str, db: Session = Depends(get_db)):
    """Toggle favorite status of a story"""
    try:
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        # Toggle the favorite status
        story.is_favorite = not story.is_favorite
        db.commit()
        db.refresh(story)

        logger.info(f"Story {story_id} favorite status toggled to {story.is_favorite}")
        return story

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling favorite: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{story_id}/stats", response_model=schemas.StoryStatsResponse)
async def get_story_stats(story_id: str, db: Session = Depends(get_db)):
    """Get story statistics"""
    try:
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        # Get chapters
        chapters = db.query(models.Chapter).filter(models.Chapter.story_id == story_id).all()

        # Calculate stats
        total_chapters = len(chapters)
        total_characters = sum(c.char_count for c in chapters)
        chapters_over_9500 = sum(1 for c in chapters if c.char_count > 9500)
        chapters_under_9500 = total_chapters - chapters_over_9500
        total_censored_words = sum(c.censored_count for c in chapters)
        chapters_with_censored = sum(1 for c in chapters if c.has_censored_words)

        # Estimate duration (assuming 150 chars per minute)
        duration_minutes = total_characters / 150
        hours = int(duration_minutes // 60)
        minutes = int(duration_minutes % 60)
        estimated_duration = f"{hours}h {minutes}m"

        # Estimate cost (placeholder)
        estimated_cost = f"~{total_characters // 5000} VNĐ"

        return {
            "total_chapters": total_chapters,
            "total_characters": total_characters,
            "chapters_over_9500": chapters_over_9500,
            "chapters_under_9500": chapters_under_9500,
            "total_censored_words": total_censored_words,
            "chapters_with_censored": chapters_with_censored,
            "estimated_duration": estimated_duration,
            "estimated_cost": estimated_cost
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting story stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{story_id}/chapters", response_model=List[schemas.ChapterResponse])
async def get_story_chapters(story_id: str, db: Session = Depends(get_db)):
    """Get all chapters of a story"""
    try:
        chapters = db.query(models.Chapter).filter(
            models.Chapter.story_id == story_id
        ).order_by(models.Chapter.chapter_number).all()
        return chapters
    except Exception as e:
        logger.error(f"Error getting story chapters: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Merged Content API ==============

@router.get("/{story_id}/merged-content")
async def get_merged_content(story_id: str, db: Session = Depends(get_db)):
    """Get merged content of all chapters"""
    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # If merged_content exists, return it
    if story.merged_content:
        return {
            "story_id": story_id,
            "merged_content": story.merged_content,
            "char_count": len(story.merged_content),
            "from_cache": True
        }

    # Otherwise, generate from chapters
    chapters = db.query(models.Chapter).filter(
        models.Chapter.story_id == story_id
    ).order_by(models.Chapter.chapter_number).all()

    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found")

    # Merge all chapters - content only, headings excluded. Separate with a
    # blank line so the last word of one chapter doesn't glue onto the first of
    # the next (which TTS would then mispronounce). Must stay in sync with
    # build_orchestrator._create_story_from_file, which persists merged_content
    # for the batch-build path.
    merged_parts = []
    for chapter in chapters:
        if chapter.content and chapter.content.strip():
            merged_parts.append(chapter.content.strip())

    merged_content = "\n\n".join(merged_parts)

    return {
        "story_id": story_id,
        "merged_content": merged_content,
        "char_count": len(merged_content),
        "total_chapters": len(chapters),
        "from_cache": False
    }


@router.put("/{story_id}/merged-content")
async def save_merged_content(
    story_id: str,
    request: dict,
    db: Session = Depends(get_db)
):
    """Save merged content to database"""
    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    try:
        merged_content = request.get("merged_content", "")
        story.merged_content = merged_content
        db.commit()

        logger.info(f"Saved merged content for story {story_id}, {len(merged_content)} chars")

        return {
            "success": True,
            "story_id": story_id,
            "char_count": len(merged_content),
            "message": "Merged content saved successfully"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error saving merged content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: sync-merged-to-chapters endpoint removed because merged content
# no longer contains chapter headers, making it impossible to split back
# to individual chapters. If needed in future, consider using a different
# separator or storing chapter boundaries separately.
