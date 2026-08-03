"""One-time, idempotent migration merging the legacy ``video_presets`` table into
the unified ``build_presets`` table.

Runs at startup after ``init_db()``. Two steps, each safe to re-run:
  1. Add the ``build_presets.cfg`` column if the table pre-dates it (create_all
     never ALTERs an existing table).
  2. Copy every legacy video preset into build_presets, keyed by name so a second
     run adds nothing. Migrated rows get an empty ``video_cfg`` (Quick Build then
     falls back to defaults) and empty ``tts_config`` (default voice) until the
     user re-saves them from the wizard, which fills both.
"""
from sqlalchemy import inspect, text
from loguru import logger

from app.database import engine, SessionLocal
from app import models

_MIGRATED_OPTIONS = {"skip_spellcheck": True, "auto_clean": True, "auto_subtitle": False}


def _ensure_cfg_column() -> None:
    insp = inspect(engine)
    if "build_presets" not in insp.get_table_names():
        return  # create_all makes it fresh (with cfg) — nothing to alter
    cols = [c["name"] for c in insp.get_columns("build_presets")]
    if "cfg" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE build_presets ADD COLUMN cfg JSON"))
        logger.info("[preset-migration] added build_presets.cfg column")


def migrate_video_presets() -> None:
    try:
        _ensure_cfg_column()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[preset-migration] add cfg column failed: {e}")
        return

    if "video_presets" not in inspect(engine).get_table_names():
        return  # fresh DB, no legacy presets

    db = SessionLocal()
    try:
        existing = {name for (name,) in db.query(models.BuildPreset.name).all()}
        legacy = db.query(models.VideoPreset).all()
        added = 0
        for vp in legacy:
            if vp.name in existing:
                continue
            db.add(models.BuildPreset(
                name=vp.name,
                cfg=vp.cfg,               # FE videoConfig — wizard reloads this
                video_cfg={},             # empty → Quick Build uses render defaults
                tts_config={},            # empty → default voice
                video_folder=None,
                banner_mode="by_filename",
                options=dict(_MIGRATED_OPTIONS),
            ))
            existing.add(vp.name)
            added += 1
        if added:
            db.commit()
            logger.info(f"[preset-migration] migrated {added} video preset(s) -> build_presets")
    except Exception as e:  # noqa: BLE001
        logger.error(f"[preset-migration] migrate failed: {e}")
        db.rollback()
    finally:
        db.close()
