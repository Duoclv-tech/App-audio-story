"""Small, idempotent schema patches for columns added after a table first
shipped. ``Base.metadata.create_all`` only ever CREATEs missing tables — it never
ALTERs an existing one — so a column added to a model needs an explicit
``ALTER TABLE ADD COLUMN`` for users upgrading over an old SQLite file.

Runs at startup right after ``init_db()``. Every step checks first and is safe
to re-run on every boot.
"""
from sqlalchemy import inspect, text
from loguru import logger

from app.database import engine


def _ensure_column(table: str, column: str, ddl_type: str) -> None:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return  # create_all makes it fresh (with the column) — nothing to alter
    cols = [c["name"] for c in insp.get_columns(table)]
    if column in cols:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
    logger.info(f"[db-migration] added {table}.{column}")


def _backfill_story_batch_id() -> None:
    """Fill ``stories.batch_id`` for stories a batch created before the column
    existed, reading the link from ``build_jobs``. Without this they'd appear both
    as standalone leaves AND inside their batch group in the history feed. Only
    touches rows still NULL that have a job, so re-running is a cheap no-op."""
    insp = inspect(engine)
    tables = insp.get_table_names()
    if "stories" not in tables or "build_jobs" not in tables:
        return
    with engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE stories SET batch_id = ("
            "  SELECT bj.batch_id FROM build_jobs bj WHERE bj.story_id = stories.id LIMIT 1"
            ") WHERE batch_id IS NULL AND id IN ("
            "  SELECT story_id FROM build_jobs WHERE story_id IS NOT NULL"
            ")"
        ))
        if result.rowcount:
            logger.info(f"[db-migration] backfilled batch_id on {result.rowcount} story(ies)")


def run_light_migrations() -> None:
    """Apply every additive column patch. Failures are logged, never fatal —
    a boot must not be blocked by a patch that already ran or races another
    process."""
    patches = [
        ("stories", "batch_id", "VARCHAR(36)"),  # groups Quick Build stories in history
        ("build_batches", "config_snapshot", "JSON"),  # frozen build config for history
    ]
    for table, column, ddl in patches:
        try:
            _ensure_column(table, column, ddl)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[db-migration] {table}.{column} failed: {e}")

    try:
        _backfill_story_batch_id()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[db-migration] batch_id backfill failed: {e}")
