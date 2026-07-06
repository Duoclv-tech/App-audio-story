from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from loguru import logger
from typing import List
from datetime import datetime

from app.database import get_db
from app import models, schemas

router = APIRouter()


@router.get("/", response_model=List[schemas.VideoPresetResponse])
async def list_presets(db: Session = Depends(get_db)):
    """List all video presets, newest first."""
    try:
        return db.query(models.VideoPreset).order_by(models.VideoPreset.created_at.desc()).all()
    except Exception as e:
        logger.error(f"Error listing video presets: {e}")
        raise HTTPException(status_code=500, detail="Failed to list video presets")


@router.post("/", response_model=schemas.VideoPresetResponse)
async def create_preset(preset: schemas.VideoPresetCreate, db: Session = Depends(get_db)):
    """Create a new video preset."""
    name = preset.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Preset name is required")

    try:
        new_preset = models.VideoPreset(name=name, cfg=preset.cfg)
        db.add(new_preset)
        db.commit()
        db.refresh(new_preset)
        logger.info(f"Created video preset: {new_preset.id} ({name})")
        return new_preset
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Preset "{name}" already exists')
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create video preset: {e}")
        raise HTTPException(status_code=500, detail="Failed to create video preset")


@router.put("/{preset_id}", response_model=schemas.VideoPresetResponse)
async def update_preset(preset_id: str, payload: schemas.VideoPresetUpdate, db: Session = Depends(get_db)):
    """Update a preset's name and/or cfg. Both fields are optional."""
    preset = db.query(models.VideoPreset).filter(models.VideoPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Preset name cannot be empty")
        preset.name = new_name

    if payload.cfg is not None:
        preset.cfg = payload.cfg

    preset.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(preset)
        logger.info(f"Updated video preset: {preset_id}")
        return preset
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Preset name "{payload.name}" already exists')
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update video preset: {e}")
        raise HTTPException(status_code=500, detail="Failed to update video preset")


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str, db: Session = Depends(get_db)):
    """Delete a video preset."""
    preset = db.query(models.VideoPreset).filter(models.VideoPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    try:
        name = preset.name
        db.delete(preset)
        db.commit()
        logger.info(f"Deleted video preset: {preset_id} ({name})")
        return {"message": "Video preset deleted successfully", "id": preset_id, "name": name}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete video preset: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete video preset")
