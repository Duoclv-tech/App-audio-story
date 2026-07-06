from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from loguru import logger
from typing import List
from datetime import datetime

from app.database import get_db
from app import models, schemas

router = APIRouter()

@router.get("/", response_model=schemas.PaginatedPromptsResponse)
async def get_prompts(
    page: int = 1,
    page_size: int = 30,
    search: str = "",
    category: str = "",
    is_active: bool = None,
    db: Session = Depends(get_db)
):
    """Get all prompts (paginated with search and filter)"""
    try:
        # Calculate skip value
        skip = (page - 1) * page_size

        # Build query with filters
        query = db.query(models.Prompt)

        # Search filter
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (models.Prompt.title.like(search_term)) |
                (models.Prompt.content.like(search_term)) |
                (models.Prompt.description.like(search_term))
            )

        # Category filter
        if category:
            query = query.filter(models.Prompt.category == category)

        # Active status filter
        if is_active is not None:
            query = query.filter(models.Prompt.is_active == is_active)

        # Get total count
        total = query.count()

        # Get paginated prompts
        prompts = query.order_by(
            models.Prompt.created_at.desc()
        ).offset(skip).limit(page_size).all()

        # Calculate total pages
        total_pages = (total + page_size - 1) // page_size

        return {
            'data': prompts,
            'meta': {
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages
            }
        }
    except Exception as e:
        logger.error(f"Error fetching prompts: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch prompts")

@router.get("/categories", response_model=List[str])
async def get_categories(db: Session = Depends(get_db)):
    """Get all unique categories"""
    try:
        categories = db.query(models.Prompt.category).filter(
            models.Prompt.category.isnot(None),
            models.Prompt.category != ""
        ).distinct().all()
        return [cat[0] for cat in categories if cat[0]]
    except Exception as e:
        logger.error(f"Error fetching categories: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch categories")

@router.get("/{prompt_id}", response_model=schemas.PromptResponse)
async def get_prompt(prompt_id: str, db: Session = Depends(get_db)):
    """Get a specific prompt by ID"""
    prompt = db.query(models.Prompt).filter(models.Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt

@router.post("/", response_model=schemas.PromptResponse)
async def create_prompt(prompt: schemas.PromptCreate, db: Session = Depends(get_db)):
    """Create a new prompt"""
    logger.info(f"Creating prompt: {prompt.title}")

    try:
        new_prompt = models.Prompt(
            title=prompt.title,
            content=prompt.content,
            category=prompt.category,
            description=prompt.description,
            is_active=prompt.is_active
        )
        db.add(new_prompt)
        db.commit()
        db.refresh(new_prompt)

        logger.info(f"Created prompt: {new_prompt.id}")
        return new_prompt
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create prompt: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create prompt")

@router.put("/{prompt_id}", response_model=schemas.PromptResponse)
async def update_prompt(prompt_id: str, prompt_update: schemas.PromptUpdate, db: Session = Depends(get_db)):
    """Update a prompt"""
    logger.info(f"Updating prompt: {prompt_id}")

    # Get prompt from database
    prompt = db.query(models.Prompt).filter(models.Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    try:
        # Update fields if provided
        if prompt_update.title is not None:
            prompt.title = prompt_update.title

        if prompt_update.content is not None:
            prompt.content = prompt_update.content

        if prompt_update.category is not None:
            prompt.category = prompt_update.category

        if prompt_update.description is not None:
            prompt.description = prompt_update.description

        if prompt_update.is_active is not None:
            prompt.is_active = prompt_update.is_active

        # Update timestamp
        prompt.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(prompt)

        logger.info(f"Updated prompt: {prompt_id}")
        return prompt
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update prompt: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update prompt")

@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: str, db: Session = Depends(get_db)):
    """Delete a prompt"""
    logger.info(f"Deleting prompt: {prompt_id}")

    # Get prompt from database
    prompt = db.query(models.Prompt).filter(models.Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    try:
        db.delete(prompt)
        db.commit()

        logger.info(f"Deleted prompt: {prompt_id}")
        return {
            "message": "Prompt deleted successfully",
            "prompt_id": prompt_id,
            "title": prompt.title
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete prompt: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete prompt")
