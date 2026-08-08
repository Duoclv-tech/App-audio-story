"""
One-off migration: copy data from the old MySQL database into the desktop
app's SQLite database.

Prereqs:
  - Old MySQL running (docker compose up -d mysql) on localhost:3307
  - pymysql installed in the venv

Usage:
  python migrate_mysql_to_sqlite.py [target_sqlite_path]

By default the target is the installed desktop app's DB:
  %LOCALAPPDATA%\\AudioStory\\app.db

Idempotent: rows already present in the target (matched by primary key, or by
setting_key for settings) are skipped, so it's safe to run more than once.
Voices are NOT migrated (the app seeds its own 14 voices with fresh ids —
copying the old ones would create duplicates by code).
"""
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from loguru import logger

from app import models
from app.database import Base

SOURCE_URL = os.environ.get(
    "OLD_MYSQL_URL",
    "mysql+pymysql://truyenfull_user:truyenfull_pass@localhost:3307/truyenfull_db",
)

# Parents before children (SQLite enforces FK with cascade on delete).
COPY_ORDER = [
    models.BannedWord,
    models.Prompt,
    models.VideoPreset,
    models.Story,
    models.Chapter,
    models.AudioFile,
    models.CensoredWord,
    models.MergedAudio,
    models.Task,
    models.VideoOutput,
]


def _target_db_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "AudioStory" / "app.db"


def copy_model(Model, src, dst) -> tuple[int, int]:
    rows = src.query(Model).all()
    cols = [c.name for c in Model.__table__.columns]
    pk = inspect(Model).primary_key[0].name
    added = 0
    for r in rows:
        data = {c: getattr(r, c) for c in cols}
        if dst.get(Model, data[pk]) is not None:
            continue
        dst.add(Model(**data))
        added += 1
    dst.commit()
    return added, len(rows)


def copy_settings(src, dst) -> tuple[int, int]:
    """Settings are matched by setting_key (not the autoincrement id) so the
    user's saved values — e.g. VBEE/Gemini API keys — carry over without id
    collisions."""
    added = updated = 0
    for s in src.query(models.Setting).all():
        existing = dst.query(models.Setting).filter_by(setting_key=s.setting_key).first()
        if existing is not None:
            existing.setting_value = s.setting_value
            updated += 1
        else:
            dst.add(models.Setting(setting_key=s.setting_key, setting_value=s.setting_value))
            added += 1
    dst.commit()
    return added, updated


def main() -> int:
    target = _target_db_path()
    if not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Source (MySQL): {SOURCE_URL.split('@')[-1]}")
    logger.info(f"Target (SQLite): {target}")

    src_engine = create_engine(SOURCE_URL)
    dst_engine = create_engine(
        f"sqlite:///{target}", connect_args={"check_same_thread": False}
    )
    # Make sure the target schema exists.
    Base.metadata.create_all(bind=dst_engine)

    SrcSession = sessionmaker(bind=src_engine)
    DstSession = sessionmaker(bind=dst_engine)
    src = SrcSession()
    dst = DstSession()
    # Enable FK on the target connection.
    dst.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys=ON"))

    try:
        total_added = 0
        for Model in COPY_ORDER:
            try:
                added, seen = copy_model(Model, src, dst)
            except Exception as e:
                logger.error(f"{Model.__tablename__}: FAILED ({e})")
                dst.rollback()
                continue
            total_added += added
            logger.info(f"{Model.__tablename__:16s}: +{added} added (of {seen} in MySQL)")

        s_add, s_upd = copy_settings(src, dst)
        logger.info(f"settings        : +{s_add} added, {s_upd} updated (by key)")

        logger.success(f"Migration done. {total_added} new rows copied.")
        return 0
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    raise SystemExit(main())
