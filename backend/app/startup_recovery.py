"""Startup reconciliation for work orphaned by a crash / force-quit.

The engines that drive tasks (TTS / download / video render) live in the
process's RAM, not the database. So when a previous process is killed mid-job
(app closed, crash, power loss), two things are left dangling:

  1. `tasks` rows still marked in-progress (queued/running/processing) that no
     live engine will ever finish — the UI polls them forever.
  2. Temp `*.work` directories from the preview renderer whose `finally` cleanup
     never ran (a hard-killed daemon thread doesn't unwind).

Both are reconciled here, once, at startup — BEFORE the server accepts requests,
so there is no live task to race with. Interrupted tasks are marked **failed**
(never auto-resumed: TTS is billable and resuming risks double-charging); the UI
already treats `failed` as terminal, stops polling, and offers a retry.
"""
import shutil

from loguru import logger
from sqlalchemy import func

from app import models, paths
from app.database import SessionLocal

# In-progress states that a dead process can strand. `paused` is intentionally
# excluded: it is a deliberate user state, not a crash artifact.
_STALE_STATUSES = ["queued", "running", "processing"]

_INTERRUPT_MSG = (
    "Tiến trình bị gián đoạn do ứng dụng khởi động lại. Vui lòng chạy lại."
)


def reconcile_interrupted_tasks() -> int:
    """Mark tasks left in-progress by a previous process as failed. Returns count."""
    db = SessionLocal()
    try:
        stale = (
            db.query(models.Task)
            .filter(models.Task.status.in_(_STALE_STATUSES))
            .all()
        )
        for task in stale:
            task.status = "failed"
            task.error_message = _INTERRUPT_MSG
            task.completed_at = func.current_timestamp()
        if stale:
            db.commit()
            logger.warning(
                f"[recovery] marked {len(stale)} interrupted task(s) as failed"
            )
        return len(stale)
    except Exception as e:
        db.rollback()
        logger.error(f"[recovery] task reconcile failed: {e}")
        return 0
    finally:
        db.close()


def sweep_orphan_work_dirs() -> int:
    """Remove leftover `*.work` temp dirs from a crash. Returns count removed.

    Only the preview renderer creates these (`<output>.mp4.work`), landing in
    the preview cache; VIDEO_DIR is swept too for robustness. At startup no
    render is running, so any `*.work` present is guaranteed orphaned.
    """
    removed = 0
    for root in (paths.PREVIEW_CACHE_DIR, paths.VIDEO_DIR):
        try:
            if not root.exists():
                continue
            for work_dir in root.glob("*.work"):
                if work_dir.is_dir():
                    shutil.rmtree(work_dir, ignore_errors=True)
                    removed += 1
        except Exception as e:
            logger.error(f"[recovery] work-dir sweep failed in {root}: {e}")
    if removed:
        logger.warning(f"[recovery] removed {removed} orphaned *.work dir(s)")
    return removed


def run_startup_recovery() -> None:
    """Run all startup reconciliation steps (best-effort; never blocks boot)."""
    reconcile_interrupted_tasks()
    sweep_orphan_work_dirs()
