"""
Regenerate backend/default_seed.db — the reference DB shipped inside the .exe
and copied into a fresh install's writable DB on first run
(see app/seed.py::restore_seed_data_if_fresh).

Two modes:
  product (default) : keep ONLY curated reference data (banned words + prompts).
                      No stories / user content — for the public release.
  --full            : keep EVERYTHING (all your test stories, chapters, presets,
                      history...). Pair with bundling the storage/ folder so the
                      audio/video files resolve. For a "full dev" build.

Either way the source DB's WAL is checkpointed into a clean single file.

Usage (from repo root):
    python packaging/make_seed_db.py                      # product, source = %LOCALAPPDATA%\\TruyenFullProcessor\\app.db
    python packaging/make_seed_db.py path\\to\\app.db      # product, explicit source
    python packaging/make_seed_db.py --full               # full,    default source
    python packaging/make_seed_db.py --full path\\to\\app.db
"""
import os
import shutil
import sqlite3
import sys
import tempfile

# In product mode, only these tables survive; every other table is emptied.
KEEP = {"banned_words", "prompts"}


def default_source() -> str:
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    return os.path.join(local, "TruyenFullProcessor", "app.db")


def main() -> None:
    args = sys.argv[1:]
    full = False
    if "--full" in args:
        full = True
        args = [a for a in args if a != "--full"]
    src = args[0] if args else default_source()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(repo, "backend", "default_seed.db")

    if not os.path.isfile(src):
        sys.exit(f"Source DB not found: {src}")

    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(src, tmp)
    con = sqlite3.connect(tmp)
    con.execute("PRAGMA foreign_keys=OFF")
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]

    if not full:
        for t in tables:
            if t not in KEEP:
                con.execute(f"DELETE FROM {t}")
        con.commit()

    kept_report = sorted(KEEP) if not full else ["banned_words", "prompts", "stories"]
    for t in kept_report:
        if t in tables:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n}")

    # Fold the WAL back into the main file so the shipped .db is self-contained.
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.commit()
    con.isolation_level = None  # autocommit so VACUUM is permitted
    con.execute("VACUUM")
    con.close()

    if os.path.exists(out):
        os.remove(out)
    shutil.move(tmp, out)
    for ext in ("-wal", "-shm"):
        p = tmp + ext
        if os.path.exists(p):
            os.remove(p)
    mode = "FULL (all data)" if full else "PRODUCT (reference only)"
    print(f"Wrote {out} ({os.path.getsize(out)} bytes) — mode: {mode}")


if __name__ == "__main__":
    main()
