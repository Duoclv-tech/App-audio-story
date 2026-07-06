from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from loguru import logger

from app.database import get_db
from app import models, schemas

router = APIRouter()

@router.get("/", response_model=List[schemas.SettingResponse])
async def get_settings(db: Session = Depends(get_db)):
    """Get all settings"""
    settings = db.query(models.Setting).all()
    return settings

@router.put("/")
async def update_settings(settings_data: dict, db: Session = Depends(get_db)):
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
