from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from loguru import logger
from typing import List
from datetime import datetime

from app.database import get_db
from app import models, schemas

router = APIRouter()

# Fields a client may set directly on a preset (name is handled separately).
_SETTABLE = (
    "tts_config", "video_cfg", "video_folder", "bgm_path",
    "watermark_image", "banner_mode", "banner_fixed", "options",
)


@router.get("/", response_model=List[schemas.BuildPresetResponse])
async def list_presets(db: Session = Depends(get_db)):
    """List all build presets, newest first."""
    try:
        return db.query(models.BuildPreset).order_by(models.BuildPreset.created_at.desc()).all()
    except Exception as e:
        logger.error(f"Error listing build presets: {e}")
        raise HTTPException(status_code=500, detail="Failed to list build presets")


@router.post("/", response_model=schemas.BuildPresetResponse)
async def create_preset(preset: schemas.BuildPresetCreate, db: Session = Depends(get_db)):
    """Create a new build preset."""
    name = preset.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Preset name is required")

    try:
        new_preset = models.BuildPreset(
            name=name,
            tts_config=preset.tts_config,
            video_cfg=preset.video_cfg,
            video_folder=preset.video_folder,
            bgm_path=preset.bgm_path,
            watermark_image=preset.watermark_image,
            banner_mode=preset.banner_mode or "by_filename",
            banner_fixed=preset.banner_fixed,
            options=preset.options,
        )
        db.add(new_preset)
        db.commit()
        db.refresh(new_preset)
        logger.info(f"Created build preset: {new_preset.id} ({name})")
        return new_preset
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Preset "{name}" already exists')
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create build preset: {e}")
        raise HTTPException(status_code=500, detail="Failed to create build preset")


@router.put("/{preset_id}", response_model=schemas.BuildPresetResponse)
async def update_preset(preset_id: str, payload: schemas.BuildPresetUpdate, db: Session = Depends(get_db)):
    """Update a build preset. Every field is optional (patch semantics)."""
    preset = db.query(models.BuildPreset).filter(models.BuildPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Preset name cannot be empty")
        preset.name = new_name

    for field in _SETTABLE:
        value = getattr(payload, field)
        if value is not None:
            setattr(preset, field, value)

    preset.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(preset)
        logger.info(f"Updated build preset: {preset_id}")
        return preset
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Preset name "{payload.name}" already exists')
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update build preset: {e}")
        raise HTTPException(status_code=500, detail="Failed to update build preset")


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str, db: Session = Depends(get_db)):
    """Delete a build preset."""
    preset = db.query(models.BuildPreset).filter(models.BuildPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    try:
        name = preset.name
        db.delete(preset)
        db.commit()
        logger.info(f"Deleted build preset: {preset_id} ({name})")
        return {"message": "Build preset deleted successfully", "id": preset_id, "name": name}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete build preset: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete build preset")
