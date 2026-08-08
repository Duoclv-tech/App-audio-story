from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from loguru import logger

from app.database import get_db
from app import models, schemas
from app.api.video import require_local_origin
from app.services.output_delivery import get_output_folder, default_output_folder

router = APIRouter()

@router.get("/", response_model=List[schemas.SettingResponse])
async def get_settings(db: Session = Depends(get_db)):
    """Get all settings"""
    settings = db.query(models.Setting).all()
    return settings

@router.get("/output-folder")
async def get_output_folder_info(db: Session = Depends(get_db)):
    """Resolve the effective output folder (where finished files are saved).

    Returns the currently configured folder, whether it is the default, and the
    default Downloads path — so the Settings UI can show what's in effect.
    """
    effective = get_output_folder(db)
    default = default_output_folder()
    return {
        "path": str(effective),
        "default": str(default),
        "is_default": str(effective) == str(default),
    }

@router.put("/")
async def update_settings(
    settings_data: dict,
    db: Session = Depends(get_db),
    _: None = Depends(require_local_origin),   # CSRF: chặn ghi key/settings từ web ngoài
):
    """Update settings"""
    for key, value in settings_data.items():
        setting = db.query(models.Setting).filter(models.Setting.setting_key == key).first()
        if setting:
            setting.setting_value = value
        else:
            setting = models.Setting(setting_key=key, setting_value=value)
            db.add(setting)

    db.commit()
    return {"message": "Settings updated successfully"}
