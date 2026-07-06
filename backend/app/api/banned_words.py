from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from loguru import logger
from typing import List
from datetime import datetime

from app.database import get_db
from app import models, schemas

router = APIRouter()

@router.get("/", response_model=schemas.PaginatedBannedWordsResponse)
async def get_banned_words(
    page: int = 1,
    page_size: int = 30,
    search: str = "",
    is_active: bool = None,
    db: Session = Depends(get_db)
):
    """Get all banned words (paginated with search and filter)"""
    try:
        # Calculate skip value
        skip = (page - 1) * page_size

        # Build query with filters
        query = db.query(models.BannedWord)

        # Search filter
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (models.BannedWord.banned_word.like(search_term)) |
                (models.BannedWord.replacement_word.like(search_term)) |
                (models.BannedWord.description.like(search_term))
            )

        # Active status filter
        if is_active is not None:
            query = query.filter(models.BannedWord.is_active == is_active)

        # Get total count
        total = query.count()

        # Get paginated banned words
        banned_words = query.order_by(
            models.BannedWord.banned_word
        ).offset(skip).limit(page_size).all()

        # Calculate total pages
        total_pages = (total + page_size - 1) // page_size

        return {
            'data': banned_words,
            'meta': {
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages
            }
        }
    except Exception as e:
        logger.error(f"Error fetching banned words: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch banned words")

@router.get("/{word_id}", response_model=schemas.BannedWordResponse)
async def get_banned_word(word_id: str, db: Session = Depends(get_db)):
    """Get a specific banned word by ID"""
    banned_word = db.query(models.BannedWord).filter(models.BannedWord.id == word_id).first()
    if not banned_word:
        raise HTTPException(status_code=404, detail="Banned word not found")
    return banned_word

@router.post("/", response_model=schemas.BannedWordResponse)
async def create_banned_word(banned_word: schemas.BannedWordCreate, db: Session = Depends(get_db)):
    """Create a new banned word"""
    logger.info(f"Creating banned word: {banned_word.banned_word}")

    # Check if banned word already exists
    existing = db.query(models.BannedWord).filter(
        models.BannedWord.banned_word == banned_word.banned_word
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Banned word already exists")

    try:
        new_banned_word = models.BannedWord(
            banned_word=banned_word.banned_word,
            replacement_word=banned_word.replacement_word,
            description=banned_word.description,
            is_active=banned_word.is_active
        )
        db.add(new_banned_word)
        db.commit()
        db.refresh(new_banned_word)

        logger.info(f"Created banned word: {new_banned_word.id}")
        return new_banned_word
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create banned word: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create banned word")

@router.put("/{word_id}", response_model=schemas.BannedWordResponse)
async def update_banned_word(word_id: str, banned_word_update: schemas.BannedWordUpdate, db: Session = Depends(get_db)):
    """Update a banned word"""
    logger.info(f"Updating banned word: {word_id}")

    # Get banned word from database
    banned_word = db.query(models.BannedWord).filter(models.BannedWord.id == word_id).first()
    if not banned_word:
        raise HTTPException(status_code=404, detail="Banned word not found")

    try:
        # Update fields if provided
        if banned_word_update.banned_word is not None:
            # Check if new banned_word doesn't conflict with existing ones (except itself)
            existing = db.query(models.BannedWord).filter(
                models.BannedWord.banned_word == banned_word_update.banned_word,
                models.BannedWord.id != word_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Banned word already exists")
            banned_word.banned_word = banned_word_update.banned_word

        if banned_word_update.replacement_word is not None:
            banned_word.replacement_word = banned_word_update.replacement_word

        if banned_word_update.description is not None:
            banned_word.description = banned_word_update.description

        if banned_word_update.is_active is not None:
            banned_word.is_active = banned_word_update.is_active

        # Update timestamp
        banned_word.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(banned_word)

        logger.info(f"Updated banned word: {word_id}")
        return banned_word
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update banned word: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update banned word")

@router.delete("/{word_id}")
async def delete_banned_word(word_id: str, db: Session = Depends(get_db)):
    """Delete a banned word"""
    logger.info(f"Deleting banned word: {word_id}")

    # Get banned word from database
    banned_word = db.query(models.BannedWord).filter(models.BannedWord.id == word_id).first()
    if not banned_word:
        raise HTTPException(status_code=404, detail="Banned word not found")

    try:
        db.delete(banned_word)
        db.commit()

        logger.info(f"Deleted banned word: {word_id}")
        return {
            "message": "Banned word deleted successfully",
            "word_id": word_id,
            "banned_word": banned_word.banned_word
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete banned word: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete banned word")
