#!/usr/bin/env python
"""
auto_run.py — Run the full TruyenFull pipeline for one or more story URLs.

Usage:
    python auto_run.py <url1> [<url2> ...]
    python auto_run.py --start 1 --end 50 <url1> <url2>
    python auto_run.py --no-video <url1>
    python auto_run.py --stop-after replace <url1>   # debug: stop early, dump text to logs/

What it does (per URL):
    1. Resolves story title from the URL
    2. Creates a Story DB record
    3. Downloads chapters (start..end)
    4. Auto-replaces banned words from the `banned_words` table
    5. Builds & saves merged_content
    6. Runs TTS on the merged content (VBEE)
    7. Merges audio into a single file
    8. (Optional) Renders a video using a hardcoded background folder

Imports backend services directly — no FastAPI / uvicorn needed.
Requires MySQL running (will auto-start the docker container).

Every URL's output is written to a single per-link folder under
    web_app/backend/storage/audio/<Sanitized_Title>/
        merged_audio.mp3             — TTS output (overwritten each run)
        story_raw_<ts>.txt           — text right after download (pre-replace)
        story_<ts>.txt               — text after banned-word replace
        banned_hits_<ts>.txt         — list of rules that actually matched

The run-level summary (covering all URLs in one invocation) is written to:
    web_app/auto_run_<ts>.txt
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import subprocess
import sys
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path

# Force UTF-8 stdout/stderr so Vietnamese titles & log messages don't blow up
# the Windows cp1252 console with UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================
# HARDCODED SETTINGS — edit these to taste
# ============================================================
DEFAULT_START_CHAPTER = 1
DEFAULT_END_CHAPTER = 10

# Auto-start MySQL via docker compose? (mimics start.bat)
AUTO_START_DOCKER = True
DB_READY_TIMEOUT_SECONDS = 60

# TTS — same defaults as the React UI (ProcessorPage.tsx)
TTS_CONFIG = {
    "voice_code": "hn_female_ngochuyen_full_48k-fhg",
    "audio_type": "mp3",
    "bitrate": 128,
    "speed": 1.0,
}

# VBEE credentials are read from backend/.env (NEVER hardcoded here).
# Set VBEE_APP_ID / VBEE_BEARER_TOKEN in .env. An optional second fallback
# set can be supplied via VBEE_APP_ID_2 / VBEE_BEARER_TOKEN_2 — if the first
# set fails (auth/quota/etc.) the script tries the next one automatically.
# Populated by _load_vbee_credentials() at run time (see below).
VBEE_CREDENTIALS: list[dict] = []

# Ollama AI spell-check toggle
ENABLE_SPELLCHECK_STEP = True

# Video step toggle + config
ENABLE_VIDEO_STEP = True
DEFAULT_VIDEO_SOURCE_FOLDER = ""   # set to a folder of .mp4 clips, otherwise step is skipped
DEFAULT_BANNER_IMAGE = ""          # optional overlay; "" = none
VIDEO_CONFIG = {
    "audio_speed": 1.07,
    "transition_effect": "crossfade",
    "transition_duration": 0.5,
    "resolution": "1920x1080",
    "banner_video_scale": 1.0,
}
# ============================================================


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR / "backend"
DOCKER_DIR = SCRIPT_DIR / "docker"

# Make `from app...` imports work, and ensure config.py reads backend/.env
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)


def _load_vbee_credentials() -> list[dict]:
    """Load VBEE credentials from backend/.env (never hardcoded in this file).

    Reads VBEE_APP_ID / VBEE_BEARER_TOKEN as the primary set, plus an optional
    fallback set from VBEE_APP_ID_2 / VBEE_BEARER_TOKEN_2. Returns them in the
    order they should be tried.
    """
    from dotenv import load_dotenv  # bundled dependency (see requirements.txt)

    # .env lives in backend/ (same file config.py reads).
    load_dotenv(BACKEND_DIR / ".env")

    creds: list[dict] = []
    for id_key, token_key in (
        ("VBEE_APP_ID", "VBEE_BEARER_TOKEN"),
        ("VBEE_APP_ID_2", "VBEE_BEARER_TOKEN_2"),
    ):
        app_id = os.getenv(id_key)
        token = os.getenv(token_key)
        if app_id and token:
            creds.append({"app_id": app_id, "bearer_token": token})
    return creds


def _silence_sqlalchemy() -> None:
    """Suppress SQLAlchemy query echo. .env has DEBUG=True which makes the
    engine echo every query — 600+ lines per run. Must be called AFTER
    `app.database` is imported because create_engine(echo=True) enables echo
    on the engine instance and installs its own logger handler."""
    # Turn off echo directly on the engine instance
    try:
        from app.database import engine
        engine.echo = False
    except Exception:
        pass
    # Belt and suspenders: also crank down every sqlalchemy logger
    for name in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine",
                 "sqlalchemy.pool", "sqlalchemy.dialects"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _nfc(s):
    """Normalize a string to Unicode NFC.

    Vietnamese text can be encoded as NFC (ế = 1 codepoint) or NFD
    (e + combining circumflex + combining acute = 3 codepoints). The two
    look identical but `"giết" in text` returns False across the boundary.
    We normalize both banned-word rules and chapter content before matching
    so replace / scan work regardless of the crawler's encoding choice.
    """
    if not isinstance(s, str):
        return s
    return unicodedata.normalize("NFC", s)


# Stop-after stages — ordered by pipeline step. The pipeline halts cleanly
# immediately after the named stage completes and dumps a debug file.
STOP_STAGES = ["download", "replace", "merge-text", "spellcheck", "tts"]


def _story_output_dir(title: str) -> Path:
    """Return (and mkdir) the per-link folder where all artefacts for a URL
    live. Mirrors the path logic used by the TTS processor
    (tts_processor.py:591), so the mp3 file and our log dumps end up
    together in the same folder.
    """
    # Deferred — config isn't importable until CWD is set to backend/
    from app.config import settings

    folder_name = (
        (title or "unknown").replace(" ", "_").replace("/", "_").replace("\\", "_")
        or "unknown_story"
    )
    path = Path(settings.STORAGE_PATH) / "audio" / folder_name
    path.mkdir(parents=True, exist_ok=True)
    return path


class PipelineStop(Exception):
    """Raised to halt the pipeline at a user-requested debug checkpoint.

    Carries the path of the debug dump so the caller can surface it in the
    summary report.
    """

    def __init__(self, stage: str, dump_path: Path, scan_result: dict | None = None):
        super().__init__(f"pipeline stopped after stage '{stage}'")
        self.stage = stage
        self.dump_path = dump_path
        self.scan_result = scan_result or {}


def _dump_story_debug(
    db,
    story_id: str,
    title: str,
    url: str,
    stage: str,
    target_dir: Path,
    filename_prefix: str = "story",
) -> tuple[Path, dict]:
    """Write every chapter of the story to a human-readable text file and
    scan it for any *remaining* banned words (i.e. ones the bulk replace
    didn't catch or rules added later).

    Returns (path, scan_result).
    """
    from app import models

    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = target_dir / f"{filename_prefix}_{ts}.txt"

    chapters = (
        db.query(models.Chapter)
        .filter(models.Chapter.story_id == story_id)
        .order_by(models.Chapter.chapter_number)
        .all()
    )
    banned = (
        db.query(models.BannedWord)
        .filter(models.BannedWord.is_active == True)  # noqa: E712
        .all()
    )

    # Scan — find any banned word still present in any chapter.
    # NFC-normalize both sides so the scan works on raw (pre-replace) dumps
    # where chapter content may still be NFD-encoded from the crawler.
    norm_banned = [
        (_nfc(bw.banned_word), bw.replacement_word)
        for bw in banned
        if bw.banned_word
    ]
    remaining: list[dict] = []
    for ch in chapters:
        content = _nfc(ch.content or "")
        for word, replacement in norm_banned:
            if word in content:
                remaining.append({
                    "chapter_number": ch.chapter_number,
                    "chapter_id": ch.id,
                    "word": word,
                    "replacement": replacement,
                    "occurrences": content.count(word),
                })

    total_chars = sum(len(c.content or "") for c in chapters)

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"STORY DEBUG DUMP  —  stopped after: {stage}  ({datetime.now():%Y-%m-%d %H:%M:%S})")
    lines.append("=" * 78)
    lines.append(f"title:       {title}")
    lines.append(f"url:         {url}")
    lines.append(f"story_id:    {story_id}")
    lines.append(f"chapters:    {len(chapters)}")
    lines.append(f"total chars: {total_chars:,}")
    lines.append(f"banned-word rules active: {len(banned)}")
    lines.append("")
    lines.append("-" * 78)
    lines.append("BANNED-WORD SCAN (against current chapter content):")
    if not remaining:
        lines.append("  CLEAN — no banned words found in downloaded content.")
    else:
        lines.append(f"  FOUND {len(remaining)} remaining matches "
                     f"across {len({r['chapter_number'] for r in remaining})} chapters:")
        for r in remaining[:100]:  # cap to first 100 so the file stays readable
            lines.append(
                f"    - ch {r['chapter_number']:>3}: {r['occurrences']}x "
                f"'{r['word']}'  ->  '{r['replacement']}'"
            )
        if len(remaining) > 100:
            lines.append(f"    ... and {len(remaining) - 100} more")
    lines.append("")

    for ch in chapters:
        lines.append("=" * 78)
        header = f"CHAPTER {ch.chapter_number}"
        if ch.title:
            header += f": {ch.title}"
        lines.append(header)
        lines.append(f"({ch.char_count or 0:,} chars)")
        lines.append("-" * 78)
        lines.append(ch.content or "(empty)")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")

    scan_result = {
        "total_remaining_matches": len(remaining),
        "affected_chapters": len({r["chapter_number"] for r in remaining}),
        "total_chars": total_chars,
        "chapters": len(chapters),
    }
    return path, scan_result


def _write_banned_hits_log(
    title: str,
    url: str,
    story_id: str,
    stage: str,
    repl: dict,
    target_dir: Path,
) -> Path:
    """Write a dedicated file listing every banned-word replacement that
    was applied in the replace step. Always written — even when zero hits
    — so the per-link folder always contains a record.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = target_dir / f"banned_hits_{ts}.txt"

    hits = repl.get("hits") or []
    total = repl.get("total_replacements", 0)
    chapters_modified = repl.get("chapters_modified", 0)
    rule_count = repl.get("banned_count", 0)

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"BANNED-WORD REPLACE LOG  ({datetime.now():%Y-%m-%d %H:%M:%S})")
    lines.append("=" * 78)
    lines.append(f"title:             {title}")
    lines.append(f"url:               {url}")
    lines.append(f"story_id:          {story_id}")
    lines.append(f"stage:             {stage}")
    lines.append(f"active rules:      {rule_count}")
    lines.append(f"chapters modified: {chapters_modified}")
    lines.append(f"total replacements:{total}")
    lines.append("-" * 78)

    if not hits:
        lines.append("CLEAN — no banned words matched during replace.")
    else:
        lines.append(f"{'WORD':<30} {'REPLACEMENT':<30} {'COUNT':>6}   CHAPTERS")
        lines.append("-" * 78)
        # Most-hit first
        for h in sorted(hits, key=lambda x: -x["count"]):
            chs = ",".join(str(c) for c in h["chapters"])
            word = h["word"]
            repl_word = h["replacement"]
            # truncate display only — file is utf-8
            lines.append(
                f"{word[:30]:<30} {repl_word[:30]:<30} {h['count']:>6}   {chs}"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _slug_from_url(url: str) -> str:
    """Extract a usable title from a story URL when get_story_info fails.

    Examples:
        https://metruyen.fit/truyen/mieng-luoi-cung-ran/  ->  Mieng Luoi Cung Ran
        https://truyenfull.vision/story-name/             ->  Story Name
    """
    try:
        path = re.sub(r"^https?://[^/]+/", "", url).strip("/")
        # last non-empty path segment
        slug = [p for p in path.split("/") if p][-1]
        slug = re.sub(r"[-_]+", " ", slug).strip()
        return slug.title() if slug else ""
    except Exception:
        return ""


# ------------------------------------------------------------
# MySQL bootstrap
# ------------------------------------------------------------
def ensure_mysql_running() -> None:
    """`docker compose up -d mysql` then poll until the DB accepts connections."""
    if AUTO_START_DOCKER:
        print("[boot] Starting MySQL container via docker compose...")
        try:
            subprocess.run(
                ["docker", "compose", "up", "-d", "mysql"],
                cwd=DOCKER_DIR,
                check=True,
            )
        except FileNotFoundError:
            print("[boot] ERROR: 'docker' not found on PATH")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"[boot] ERROR: docker compose failed: {e}")
            sys.exit(1)

    # Deferred import so config.py reads CWD-relative .env
    from app.database import test_connection

    # Engine is created at import time with echo=True; silence it now.
    _silence_sqlalchemy()

    print("[boot] Waiting for MySQL to accept connections...")
    deadline = time.time() + DB_READY_TIMEOUT_SECONDS
    while time.time() < deadline:
        if test_connection():
            print("[boot] MySQL ready.")
            return
        time.sleep(2)
    print("[boot] ERROR: MySQL did not become ready in time")
    sys.exit(1)


# ------------------------------------------------------------
# Banned-word auto replacement
# ------------------------------------------------------------
def auto_replace_banned_words(db, story_id: str) -> dict:
    """Apply every active row in `banned_words` to every chapter of the story.

    Mirrors what the per-word `accept_replacement` endpoint does, but in bulk.
    """
    from app import models

    banned = (
        db.query(models.BannedWord)
        .filter(models.BannedWord.is_active == True)  # noqa: E712
        .all()
    )
    if not banned:
        return {"chapters_modified": 0, "total_replacements": 0, "banned_count": 0}

    # Build NFC-normalized rule set, sorted by word length DESC so longer
    # phrases match before their substrings (prevents 'giết' from clobbering
    # 'giết người' when both rules exist). NFC normalization lets us match
    # even when crawled text was NFD-encoded.
    normalized_rules = []
    for bw in banned:
        if not bw.banned_word:
            continue
        normalized_rules.append({
            "word": _nfc(bw.banned_word),
            "replacement": _nfc(bw.replacement_word or ""),
        })
    normalized_rules.sort(key=lambda r: len(r["word"]), reverse=True)

    chapters = (
        db.query(models.Chapter)
        .filter(models.Chapter.story_id == story_id)
        .all()
    )

    total_replacements = 0
    chapters_modified = 0
    # Per-rule aggregate: word -> {replacement, count, chapters: set}
    hits: dict = {}

    for ch in chapters:
        if not ch.content:
            continue
        # Normalize once up-front so NFC rules match reliably. Store the
        # normalized form back to DB (visually identical, just consistent
        # encoding — keeps TTS / downstream dumps in one canonical form).
        normalized = _nfc(ch.content)
        new_content = normalized
        for rule in normalized_rules:
            if rule["word"] in new_content:
                n = new_content.count(rule["word"])
                total_replacements += n
                new_content = new_content.replace(rule["word"], rule["replacement"])
                entry = hits.setdefault(
                    rule["word"],
                    {"replacement": rule["replacement"], "count": 0, "chapters": set()},
                )
                entry["count"] += n
                entry["chapters"].add(ch.chapter_number)

        # Persist any change (either real replacement or pure NFC normalize),
        # but only count the chapter as "modified" when a rule actually fired.
        if new_content != ch.content:
            ch.content = new_content
            ch.char_count = len(new_content)
        if new_content != normalized:
            ch.has_censored_words = False
            ch.censored_count = 0
            chapters_modified += 1

    db.commit()

    # Per-rule detail log — most frequent first
    if hits:
        sorted_hits = sorted(hits.items(), key=lambda kv: -kv[1]["count"])
        for word, info in sorted_hits:
            chs = sorted(info["chapters"])
            chs_str = ",".join(str(c) for c in chs)
            print(
                f"  [replace]      '{word}' -> '{info['replacement']}'  "
                f"x{info['count']}  (ch {chs_str})"
            )

    return {
        "chapters_modified": chapters_modified,
        "total_replacements": total_replacements,
        "banned_count": len(banned),
        "hits": [
            {
                "word": w,
                "replacement": info["replacement"],
                "count": info["count"],
                "chapters": sorted(info["chapters"]),
            }
            for w, info in hits.items()
        ],
    }


# ------------------------------------------------------------
# AI spell-check (runs on merged text) — OpenAI only
# ------------------------------------------------------------
MAX_SPELLCHECK_PASSES = 2


def auto_spellcheck_merged(db, story_id: str, merged: str,
                           story_dir: Path | None = None) -> dict:
    """Run OpenAI spell-check on the merged text in multiple passes until
    clean (or MAX_SPELLCHECK_PASSES reached). Apply fixes back to both
    story.merged_content and individual chapters.

    Args:
        db: DB session
        story_id: story to check
        merged: the merged_content string (already built in step 4)
        story_dir: folder to write spellcheck log (storage/audio/<Title>/)

    Returns a result dict with total_fixes, all_hits list, and the corrected
    merged text.
    """
    from app import models
    from app.services.openai_spellcheck import OpenAISpellChecker

    checker = OpenAISpellChecker()
    if not checker.is_available():
        return {"skipped": True, "reason": "OPENAI_API_KEY not set",
                "total_fixes": 0, "merged": merged}

    print(f"  [spellcheck] using OpenAI ({checker.model})")

    current_text = _nfc(merged)
    grand_total_fixes = 0
    all_applied: list[dict] = []

    for pass_num in range(1, MAX_SPELLCHECK_PASSES + 1):
        print(f"  [spellcheck] pass {pass_num}/{MAX_SPELLCHECK_PASSES}...")
        hits = checker.find_misspelled_words(current_text)
        if not hits:
            print(f"  [spellcheck] pass {pass_num}: CLEAN — no errors found")
            break

        # Apply fixes
        pass_fixes = 0
        for hit in hits:
            wrong = hit["wrong"]
            correct = hit["correct"]
            if wrong in current_text:
                n = current_text.count(wrong)
                current_text = current_text.replace(wrong, correct)
                pass_fixes += n
                all_applied.append({
                    "wrong": wrong,
                    "correct": correct,
                    "explanation": hit.get("explanation", ""),
                    "count": n,
                    "pass": pass_num,
                })
                print(f"    [{pass_num}] '{wrong}' -> '{correct}' x{n}  ({hit.get('explanation', '')})")

        grand_total_fixes += pass_fixes
        print(f"  [spellcheck] pass {pass_num}: {pass_fixes} fix(es)")

        if pass_fixes == 0:
            break

    # Write corrected merged_content back to story
    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if story:
        story.merged_content = current_text

    # Apply all fixes to individual chapters so they stay in sync
    chapters = (
        db.query(models.Chapter)
        .filter(models.Chapter.story_id == story_id)
        .all()
    )
    for ch in chapters:
        if not ch.content:
            continue
        content = _nfc(ch.content)
        new_content = content
        for fix in all_applied:
            if fix["wrong"] in new_content:
                new_content = new_content.replace(fix["wrong"], fix["correct"])
        if new_content != ch.content:
            ch.content = new_content
            ch.char_count = len(new_content)

    # Add new banned words from spellcheck hits
    added_banned = 0
    for fix in all_applied:
        wrong = fix["wrong"]
        correct = fix["correct"]
        # Skip if already exists in banned_words
        exists = (
            db.query(models.BannedWord)
            .filter(models.BannedWord.banned_word == wrong)
            .first()
        )
        if exists:
            continue
        bw = models.BannedWord(
            banned_word=wrong,
            replacement_word=correct,
            description=f"[auto-spellcheck] {fix.get('explanation', '')}",
            is_active=True,
        )
        db.add(bw)
        added_banned += 1
    if added_banned:
        print(f"  [spellcheck] added {added_banned} new banned word(s)")

    db.commit()

    # Write spellcheck results to file in story_dir
    log_path = None
    if story_dir and all_applied:
        story_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = story_dir / f"spellcheck_{ts}.txt"
        lines = [
            f"Spellcheck results — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Story ID: {story_id}",
            f"Model: OpenAI ({checker.model})",
            f"Total fixes: {grand_total_fixes}",
            f"Passes used: {min(pass_num, MAX_SPELLCHECK_PASSES)}",
            "=" * 60,
            "",
        ]
        for i, fix in enumerate(all_applied, 1):
            lines.append(f"{i:3d}. [pass {fix['pass']}] '{fix['wrong']}'")
            lines.append(f"  -> '{fix['correct']}'  x{fix['count']}")
            lines.append(f"     {fix['explanation']}")
            lines.append("")
        log_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  [spellcheck] log -> {log_path}")

    return {
        "skipped": False,
        "total_fixes": grand_total_fixes,
        "hits": all_applied,
        "merged": current_text,
        "log_path": str(log_path) if log_path else None,
    }


# ------------------------------------------------------------
# TTS with hardcoded credential fallback
# ------------------------------------------------------------
async def _tts_with_fallback(db, task_id: str, story_id: str) -> dict:
    """Run merged-content TTS with hardcoded VBEE credentials, falling back
    through VBEE_CREDENTIALS on failure. Updates the Task record like the
    real worker does, so DB state stays consistent with the rest of the app.
    """
    from app import models
    from app.services.tts_processor import VbeeTTSProcessor

    if not VBEE_CREDENTIALS:
        return {"success": False, "error": "VBEE_CREDENTIALS list is empty"}

    # Mark task as running
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.status = "running"
        db.commit()

    last_error: str | None = None
    for idx, cred in enumerate(VBEE_CREDENTIALS, 1):
        masked = (cred["app_id"][:8] + "…") if cred.get("app_id") else "?"
        print(f"  [tts]        attempt {idx}/{len(VBEE_CREDENTIALS)} (app_id={masked})")
        try:
            processor = VbeeTTSProcessor(
                app_id=cred["app_id"],
                bearer_token=cred["bearer_token"],
                # Note: NOT passing db= here, so DB-stored credentials don't
                # override our hardcoded values.
            )
            result = await processor.process_merged_content(
                story_id=story_id,
                db=db,
                voice_code=TTS_CONFIG["voice_code"],
                audio_type=TTS_CONFIG["audio_type"],
                bitrate=TTS_CONFIG["bitrate"],
                speed=TTS_CONFIG["speed"],
            )
        except Exception as e:
            last_error = f"exception with creds #{idx}: {e}"
            print(f"  [tts]        attempt {idx} raised: {e}")
            continue

        if result.get("success"):
            if task:
                task.status = "completed"
                task.completed_items = 1
                task.progress = 100
                db.commit()
            result["credential_index"] = idx
            return result

        last_error = f"creds #{idx}: {result.get('error', 'unknown error')}"
        print(f"  [tts]        attempt {idx} failed: {result.get('error')}")

    # All credential sets exhausted
    if task:
        task.status = "failed"
        task.error_message = last_error or "all VBEE credentials failed"
        db.commit()
    return {"success": False, "error": last_error or "all VBEE credentials failed"}


# ------------------------------------------------------------
# Per-URL pipeline
# ------------------------------------------------------------
async def run_pipeline_for_url(
    url: str,
    start: int,
    end: int,
    stop_after: str | None = None,
) -> dict:
    """Execute the full pipeline for a single URL. Never raises — returns a result dict.

    If `stop_after` is set (one of STOP_STAGES), the pipeline halts cleanly
    after that stage completes, dumps the current chapter content to a debug
    text file, and marks the result as "stopped" (not a failure).
    """
    from app.database import SessionLocal
    from app import models
    from app.services.downloader import StoryDownloader
    from app.workers.download_worker import download_chapters_task
    from app.workers.video_worker import process_video_task

    result: dict = {
        "url": url,
        "title": None,
        "story_id": None,
        "start": start,
        "end": end,
        "steps": {},          # step name -> info dict
        "output_dir": None,    # per-link folder (storage/audio/<Title>/)
        "final_audio": None,
        "final_video": None,
        "success": False,
        "stopped": False,
        "stop_stage": None,
        "raw_dump": None,      # <output_dir>/story_raw_<ts>.txt
        "debug_dump": None,    # <output_dir>/story_<ts>.txt
        "banned_log": None,    # <output_dir>/banned_hits_<ts>.txt
        "error": None,
    }

    db = SessionLocal()
    try:
        # ----- Step 1: title + Story record -----
        try:
            info = StoryDownloader(url).get_story_info()
            raw_title = (info.get("title") or "").strip()
            author = info.get("author")
        except Exception as e:
            print(f"  [info] could not fetch story info ({e})")
            raw_title = ""
            author = None

        # Fall back to URL slug if get_story_info failed or returned "Unknown".
        # Required to avoid every story landing in storage/audio/Unknown/ and
        # overwriting each other.
        if not raw_title or raw_title.lower() == "unknown":
            slug_title = _slug_from_url(url)
            title = slug_title or f"AutoRun {datetime.now():%Y%m%d_%H%M%S}"
        else:
            title = raw_title

        result["title"] = title
        print(f"  title:  {title}")

        # Per-link output folder (mirrors the TTS processor path).
        # All artefacts for this URL land here: mp3 + log files.
        story_dir = _story_output_dir(title)
        result["output_dir"] = str(story_dir)
        print(f"  folder: {story_dir}")

        story = models.Story(
            title=title,
            url=url,
            author=author,
            start_chapter=start,
            end_chapter=end,
            status="created",
            current_step=1,
        )
        db.add(story)
        db.commit()
        db.refresh(story)
        story_id = story.id
        result["story_id"] = story_id

        # ----- Step 2: Download -----
        print("  [download]   starting...")
        task_dl = models.Task(
            story_id=story_id,
            type="download",
            status="queued",
            total_items=end - start + 1,
        )
        db.add(task_dl)
        db.commit()
        db.refresh(task_dl)

        dl = await download_chapters_task(task_dl.id, story_id, start, end)
        if not dl.get("success"):
            raise RuntimeError(f"download failed: {dl.get('error')}")
        if dl.get("successful", 0) == 0:
            raise RuntimeError("download returned 0 successful chapters")
        # The download worker used its own SessionLocal and committed chapters
        # to the DB. Our pipeline session is still inside its first implicit
        # transaction (started at the earlier Story/Task INSERTs), so under
        # MySQL REPEATABLE READ it sees a frozen snapshot from BEFORE those
        # chapters existed. Commit to end the stale transaction so the next
        # query gets a fresh snapshot.
        db.commit()
        result["steps"]["download"] = {
            "ok": True,
            "successful": dl.get("successful", 0),
            "failed": dl.get("failed", 0),
            "total": dl.get("total", 0),
        }
        print(f"  [download]   OK ({dl.get('successful')}/{dl.get('total')})")

        # ALWAYS dump the raw downloaded text (pre-replace snapshot), even in
        # full-pipeline mode, so you always have a record of what was fetched.
        raw_dump_path, raw_scan = _dump_story_debug(
            db, story_id, title, url, "download",
            target_dir=story_dir,
            filename_prefix="story_raw",
        )
        result["raw_dump"] = str(raw_dump_path)
        print(f"  [dump]       raw    -> {raw_dump_path}")

        if stop_after == "download":
            raise PipelineStop("download", raw_dump_path, raw_scan)

        # ----- Step 3: Auto-replace banned words -----
        print("  [replace]    applying banned-word replacements...")
        repl = auto_replace_banned_words(db, story_id)
        result["steps"]["banned_replace"] = {"ok": True, **repl}
        print(
            f"  [replace]    OK ({repl['total_replacements']} replacements "
            f"in {repl['chapters_modified']} chapters; "
            f"{repl['banned_count']} rules)"
        )

        # ALWAYS dump post-replace story text + banned-hits log, regardless
        # of stop_after, so you always have a reviewable record.
        story_dump_path, scan = _dump_story_debug(
            db, story_id, title, url, "replace",
            target_dir=story_dir,
            filename_prefix="story",
        )
        banned_log_path = _write_banned_hits_log(
            title, url, story_id, "replace", repl,
            target_dir=story_dir,
        )
        result["debug_dump"] = str(story_dump_path)
        result["banned_log"] = str(banned_log_path)
        print(f"  [dump]       story  -> {story_dump_path}")
        print(f"  [dump]       banned -> {banned_log_path}")

        if stop_after == "replace":
            raise PipelineStop("replace", story_dump_path, scan)

        # ----- Step 4: Build & save merged content -----
        print("  [merge-text] building merged_content...")
        chapters = (
            db.query(models.Chapter)
            .filter(models.Chapter.story_id == story_id)
            .order_by(models.Chapter.chapter_number)
            .all()
        )
        merged = "".join((c.content or "").strip() for c in chapters)

        # Re-fetch story since download worker mutated it via another session
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        story.merged_content = merged
        story.current_step = 5
        story.status = "ready_for_tts"
        db.commit()
        result["steps"]["merge_text"] = {"ok": True, "char_count": len(merged)}
        print(f"  [merge-text] OK ({len(merged):,} chars)")

        if stop_after == "merge-text":
            dump_path, scan = _dump_story_debug(db, story_id, title, url, "merge-text")
            raise PipelineStop("merge-text", dump_path, scan)

        # ----- Step 5: AI Spell-check on merged text (OpenAI) -----
        if ENABLE_SPELLCHECK_STEP:
            print("  [spellcheck] running OpenAI spell-check on merged text...")
            sc = auto_spellcheck_merged(db, story_id, merged, story_dir=story_dir)
            result["steps"]["spellcheck"] = {"ok": True, **{k: v for k, v in sc.items() if k != "merged"}}
            if sc.get("skipped"):
                print(f"  [spellcheck] SKIP ({sc.get('reason')})")
            else:
                # Update merged with corrected text for TTS
                merged = sc["merged"]
                fixes = sc.get("total_fixes", 0)
                print(f"  [spellcheck] OK — {fixes} fix(es) applied")
                # Show each fix
                for h in sc.get("hits", []):
                    print(f"               '{h['wrong']}' -> '{h['correct']}' x{h['count']}")
                    print(f"               reason: {h.get('explanation', '')}")
        else:
            result["steps"]["spellcheck"] = {"ok": False, "skipped": True, "reason": "disabled"}
            print("  [spellcheck] SKIP (disabled)")

        if stop_after == "spellcheck":
            ts_sc = datetime.now().strftime("%Y%m%d_%H%M%S")
            sc_dump_path = story_dir / f"story_spellcheck_{ts_sc}.txt"
            sc_dump_path.write_text(merged, encoding="utf-8")
            print(f"  [dump]       spellcheck story -> {sc_dump_path}")
            raise PipelineStop("spellcheck", sc_dump_path)

        if not merged.strip():
            raise RuntimeError("merged_content is empty after download — nothing to TTS")

        # ----- Step 6: TTS (merged, with hardcoded credentials + fallback) -----
        print("  [tts]        calling VBEE...")
        task_tts = models.Task(story_id=story_id, type="tts", status="queued")
        db.add(task_tts)
        db.commit()
        db.refresh(task_tts)

        tts = await _tts_with_fallback(db, task_tts.id, story_id)
        if not tts.get("success"):
            raise RuntimeError(f"TTS failed: {tts.get('error')}")
        result["steps"]["tts"] = {
            "ok": True,
            "credential_index": tts.get("credential_index"),
        }
        print(f"  [tts]        OK (creds #{tts.get('credential_index')})")

        # Always stop after TTS — skip video generation
        dump_path, scan = _dump_story_debug(
            db, story_id, title, url, "tts",
            target_dir=story_dir,
            filename_prefix="story_tts",
        )
        print("  [pipeline]   STOP after TTS (video skipped)")
        result["stopped"] = True
        result["stop_stage"] = "tts"
        result["success"] = True
        result["debug_dump"] = str(dump_path)
        return result

        # ----- Step 7: Locate the merged audio file -----
        # process_merged_content already produces a single MergedAudio row +
        # mp3 file, so there is no separate audio_merge worker call (this
        # mirrors the React UI workflow which jumps from TTS straight to Video).
        merged_audio = (
            db.query(models.MergedAudio)
            .filter(models.MergedAudio.story_id == story_id)
            .order_by(models.MergedAudio.created_at.desc())
            .first()
        )
        if not merged_audio or not merged_audio.file_path:
            raise RuntimeError("TTS reported success but no MergedAudio row was created")
        final_audio_path = merged_audio.file_path
        result["steps"]["audio_file"] = {
            "ok": True,
            "output_path": final_audio_path,
            "file_size": merged_audio.file_size,
        }
        result["final_audio"] = final_audio_path
        print(f"  [audio]      OK -> {final_audio_path}")

        # ----- Step 8: Video (optional) -----
        if ENABLE_VIDEO_STEP:
            if not DEFAULT_VIDEO_SOURCE_FOLDER:
                msg = "DEFAULT_VIDEO_SOURCE_FOLDER not configured"
                result["steps"]["video"] = {"ok": False, "skipped": True, "reason": msg}
                print(f"  [video]      SKIP ({msg})")
            else:
                print("  [video]      rendering...")
                task_video = models.Task(
                    story_id=story_id, type="video_processing", status="queued"
                )
                db.add(task_video)
                db.commit()
                db.refresh(task_video)

                video_cfg = {
                    "video_source_folder": DEFAULT_VIDEO_SOURCE_FOLDER,
                    "audio_path": final_audio_path,
                    **VIDEO_CONFIG,
                }
                if DEFAULT_BANNER_IMAGE:
                    video_cfg["banner_image"] = DEFAULT_BANNER_IMAGE

                vr = await process_video_task(task_video.id, story_id, video_cfg)
                if not vr.get("success"):
                    raise RuntimeError(f"video failed: {vr.get('error')}")
                # Refresh snapshot — video worker writes via its own session.
                db.commit()
                result["steps"]["video"] = {
                    "ok": True,
                    "output_path": vr.get("output_path"),
                }
                result["final_video"] = vr.get("output_path")
                print(f"  [video]      OK -> {vr.get('output_path')}")
        else:
            result["steps"]["video"] = {"ok": False, "skipped": True, "reason": "ENABLE_VIDEO_STEP=False"}
            print("  [video]      SKIP (disabled)")

        # Mark complete
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        story.status = "completed"
        story.current_step = 8
        db.commit()

        result["success"] = True
        return result

    except PipelineStop as stop:
        result["stopped"] = True
        result["stop_stage"] = stop.stage
        result["debug_dump"] = str(stop.dump_path)
        result["steps"]["debug_dump"] = {
            "ok": True,
            "stage": stop.stage,
            "path": str(stop.dump_path),
            **stop.scan_result,
        }
        print(f"  [STOP]       after '{stop.stage}'  ->  {stop.dump_path}")
        remaining = stop.scan_result.get("total_remaining_matches", 0)
        if remaining:
            print(
                f"  [STOP]       WARNING: {remaining} banned-word matches "
                f"still present in {stop.scan_result.get('affected_chapters')} chapters"
            )
        else:
            print("  [STOP]       banned-word scan: CLEAN")
        return result

    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        try:
            db.rollback()
        except Exception:
            pass
        return result
    finally:
        db.close()


# ------------------------------------------------------------
# Summary report
# ------------------------------------------------------------
def write_summary_report(results: list[dict], started_at: datetime) -> Path:
    # Summary lives at web_app/auto_run_<ts>.txt — the per-link files live
    # in each URL's storage/audio/<Title>/ folder. No logs/ folder at all.
    fname = SCRIPT_DIR / f"auto_run_{started_at:%Y%m%d_%H%M%S}.txt"

    ok_count = sum(1 for r in results if r["success"])
    stop_count = sum(1 for r in results if r.get("stopped"))
    fail_count = len(results) - ok_count - stop_count
    elapsed_min = (datetime.now() - started_at).total_seconds() / 60

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"AUTO_RUN SUMMARY  ({started_at:%Y-%m-%d %H:%M:%S})")
    lines.append(
        f"Total: {len(results)}  |  OK: {ok_count}  |  STOP: {stop_count}  "
        f"|  FAIL: {fail_count}  |  Elapsed: {elapsed_min:.1f} min"
    )
    lines.append("=" * 78)
    lines.append("")

    for i, r in enumerate(results, 1):
        if r.get("stopped"):
            status = f"STOP@{r['stop_stage']}"
        elif r["success"]:
            status = "OK  "
        else:
            status = "FAIL"
        lines.append(f"[{i:02d}] {status:<12}  {r['url']}")
        if r.get("output_dir"):
            lines.append(f"     folder:   {r['output_dir']}")
        lines.append(f"     title:    {r.get('title')}")
        lines.append(f"     story_id: {r.get('story_id')}")
        lines.append(f"     range:    chapter {r['start']}–{r['end']}")

        for step_name, info in (r.get("steps") or {}).items():
            if info.get("skipped"):
                badge = "SKIP"
            elif info.get("ok"):
                badge = "OK  "
            else:
                badge = "FAIL"

            extras = []
            if "successful" in info:
                extras.append(f"{info['successful']}/{info.get('total', '?')} chapters")
            if "char_count" in info:
                extras.append(f"{info['char_count']:,} chars")
            if "total_replacements" in info:
                extras.append(
                    f"{info['total_replacements']} replacements / "
                    f"{info['chapters_modified']} chapters"
                )
                # Render the per-rule breakdown on sub-lines
                for hit in info.get("hits") or []:
                    chs = ",".join(str(c) for c in hit["chapters"])
                    extras.append(
                        f"\n           '{hit['word']}' -> '{hit['replacement']}'"
                        f"  x{hit['count']}  (ch {chs})"
                    )
            if "output_path" in info and info["output_path"]:
                extras.append(f"-> {info['output_path']}")
            if "reason" in info:
                extras.append(f"({info['reason']})")

            extra_str = "  ".join(extras)
            lines.append(f"       {badge}  {step_name:<14}  {extra_str}")

        if r.get("final_audio"):
            lines.append(f"     audio:    {r['final_audio']}")
        if r.get("final_video"):
            lines.append(f"     video:    {r['final_video']}")
        if r.get("raw_dump"):
            lines.append(f"     raw:      {r['raw_dump']}")
        if r.get("debug_dump"):
            lines.append(f"     story:    {r['debug_dump']}")
        if r.get("banned_log"):
            lines.append(f"     banned:   {r['banned_log']}")
        dbg = (r.get("steps") or {}).get("debug_dump", {})
        rem = dbg.get("total_remaining_matches")
        if rem is not None:
            if rem == 0:
                lines.append("     scan:     CLEAN (no banned words remaining)")
            else:
                lines.append(
                    f"     scan:     {rem} banned-word matches in "
                    f"{dbg.get('affected_chapters')} chapters"
                )
        if r.get("error"):
            lines.append(f"     ERROR:    {r['error']}")
        lines.append("")

    fname.write_text("\n".join(lines), encoding="utf-8")
    return fname


# ------------------------------------------------------------
# CLI entry
# ------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the full TruyenFull pipeline for one or more story URLs.",
    )
    p.add_argument("urls", nargs="+", help="One or more story URLs")
    p.add_argument(
        "--start",
        type=int,
        default=DEFAULT_START_CHAPTER,
        help=f"Start chapter (default {DEFAULT_START_CHAPTER})",
    )
    p.add_argument(
        "--end",
        type=int,
        default=DEFAULT_END_CHAPTER,
        help=f"End chapter (default {DEFAULT_END_CHAPTER})",
    )
    p.add_argument(
        "--no-spellcheck",
        action="store_true",
        help="Skip the Ollama AI spell-check step",
    )
    p.add_argument(
        "--no-video",
        action="store_true",
        help="Skip the Video step regardless of script setting",
    )
    p.add_argument(
        "--stop-after",
        choices=STOP_STAGES,
        default=None,
        help="Debug: halt after this stage and dump chapter text + banned-word "
             "scan to logs/story_<slug>_<timestamp>.txt",
    )
    return p.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    global ENABLE_VIDEO_STEP, ENABLE_SPELLCHECK_STEP
    if args.no_spellcheck:
        ENABLE_SPELLCHECK_STEP = False
    if args.no_video:
        ENABLE_VIDEO_STEP = False

    started_at = datetime.now()
    results: list[dict] = []
    total = len(args.urls)

    for i, url in enumerate(args.urls, 1):
        print(f"\n========== [{i}/{total}] {url} ==========")
        try:
            r = await run_pipeline_for_url(
                url, args.start, args.end, stop_after=args.stop_after
            )
        except Exception as e:
            r = {
                "url": url,
                "title": None,
                "story_id": None,
                "start": args.start,
                "end": args.end,
                "steps": {},
                "output_dir": None,
                "final_audio": None,
                "final_video": None,
                "success": False,
                "stopped": False,
                "stop_stage": None,
                "raw_dump": None,
                "debug_dump": None,
                "banned_log": None,
                "error": f"unhandled: {e}",
                "traceback": traceback.format_exc(),
            }
        results.append(r)
        if r.get("stopped"):
            badge = f"STOP @ {r['stop_stage']}"
        elif r["success"]:
            badge = "OK"
        else:
            badge = "FAIL"
        print(f"========== {badge}: {url} ==========")

    report_path = write_summary_report(results, started_at)
    ok_count = sum(1 for r in results if r["success"])
    print(f"\n>>> Summary: {ok_count}/{len(results)} succeeded")
    print(f">>> Report:  {report_path}")


def main() -> None:
    global VBEE_CREDENTIALS
    args = parse_args()
    VBEE_CREDENTIALS = _load_vbee_credentials()
    if not VBEE_CREDENTIALS:
        print("[boot] ERROR: no VBEE credentials found. Set VBEE_APP_ID and "
              "VBEE_BEARER_TOKEN in backend/.env (optional fallback: "
              "VBEE_APP_ID_2 / VBEE_BEARER_TOKEN_2).")
        sys.exit(1)
    ensure_mysql_running()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n[interrupt] Aborted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
