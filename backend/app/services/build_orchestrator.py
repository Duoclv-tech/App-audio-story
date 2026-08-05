"""Quick-build orchestrator.

Runs the full wizard pipeline (import → merged content → TTS → video) for each
story file in a batch, back-to-back, with no manual review steps. Everything
runs in ONE background thread so the GPU-heavy TTS/render stages stay strictly
sequential (see gpu_guard for why). Per-file failures are isolated: a job that
throws is marked 'error' and the batch moves on to the next file.

The pipeline reuses the exact service functions the wizard endpoints call:
  - chapter_splitter.read_text_from_file / split_chapters   (import)
  - VbeeTTSProcessor / AiVoiceLocalProcessor .process_merged_content  (TTS)
  - video_worker.run_video_task                             (render)
"""
import os
import re
import json
import asyncio
import random
import subprocess
import threading
from pathlib import Path
from typing import Dict, Optional
from loguru import logger

from app.database import SessionLocal
from app import models, paths
from app.services import gpu_guard
from app.services.chapter_splitter import read_text_from_file, split_chapters
from app.services.subtitle_renderer import build_estimated_srt

DEFAULT_VBEE_VOICE = "hn_female_ngochuyen_full_48k-fhg"
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Batches the user hasn't stopped. A batch is added when its thread starts and
# checked before each job; "stop" discards it so the loop ends after the job
# currently rendering finishes (a blocking render can't be interrupted).
_running_batches: set = set()
_batches_lock = threading.Lock()


def is_batch_running(batch_id: str) -> bool:
    with _batches_lock:
        return batch_id in _running_batches


def stop_batch(batch_id: str) -> None:
    with _batches_lock:
        _running_batches.discard(batch_id)


def start_batch_thread(batch_id: str) -> None:
    """Spawn the batch worker. The caller MUST have already taken the GPU guard
    (gpu_guard.try_acquire) synchronously; _run_batch releases it when done."""
    with _batches_lock:
        _running_batches.add(batch_id)
    thread = threading.Thread(target=_run_batch, args=(batch_id,), daemon=True)
    thread.start()


# --------------------------------------------------------------------------- #
#  Text cleanup (conservative — only drop obvious junk lines)
# --------------------------------------------------------------------------- #
_JUNK_LINE_RE = re.compile(
    r"(https?://|www\.|\.com|\.net|\.vn\b|nguồn\s*:|nguồn truyện|truyện được đăng|"
    r"đọc truyện tại|vui lòng ghi rõ nguồn|converter\s*:|dịch\s*:|beta\s*:)",
    re.IGNORECASE,
)


def clean_story_text(text: str) -> str:
    """Remove obvious non-story lines (source/site/credit lines) and collapse
    runs of blank lines. Deliberately conservative — never edits sentence text."""
    if not text:
        return text
    out = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _JUNK_LINE_RE.search(line):
            continue
        out.append(line)
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _nice_title(source_path: str) -> str:
    stem = Path(source_path).stem
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem or "Truyện"


def sibling_banner(source_path: str) -> Optional[str]:
    """Path of a same-named image next to the story file, if any (banner auto)."""
    base = os.path.splitext(source_path)[0]
    for ext in _IMAGE_EXTS:
        cand = base + ext
        if os.path.exists(cand):
            return cand
    return None


def has_sibling_banner(source_path: str) -> bool:
    return sibling_banner(source_path) is not None


def _auto_banner(source_path: str, cfg: Dict) -> Optional[str]:
    mode = cfg.get("banner_mode") or "by_filename"
    if mode == "none":
        return None
    if mode == "fixed":
        fixed = cfg.get("banner_fixed")
        return fixed if fixed and os.path.exists(fixed) else None
    # by_filename: look for <same-name>.<img> next to the .txt
    return sibling_banner(source_path)


# --------------------------------------------------------------------------- #
#  Config resolution: preset + per-job overrides
# --------------------------------------------------------------------------- #
def _resolve_config(db, job: "models.BuildJob") -> Dict:
    preset = db.query(models.BuildPreset).filter(
        models.BuildPreset.id == job.preset_id
    ).first()
    if not preset:
        raise RuntimeError("Build preset không tồn tại")

    tts = dict(preset.tts_config or {})
    options = dict(preset.options or {})
    cfg = {
        "tts": tts,
        "video_cfg": dict(preset.video_cfg or {}),
        "video_folder": preset.video_folder,
        "bgm_path": preset.bgm_path,
        "watermark_image": preset.watermark_image,
        "banner_mode": preset.banner_mode or "by_filename",
        "banner_fixed": preset.banner_fixed,
        "options": options,
    }

    ov = job.overrides or {}
    # Per-job overrides only touch a small, safe set of fields.
    if ov.get("video_folder"):
        cfg["video_folder"] = ov["video_folder"]
    if ov.get("banner_mode"):
        cfg["banner_mode"] = ov["banner_mode"]
    if ov.get("banner_fixed"):
        cfg["banner_fixed"] = ov["banner_fixed"]
    if "voice_code" in ov and ov["voice_code"]:
        tts["voice_code"] = ov["voice_code"]
    if "engine" in ov and ov["engine"]:
        tts["engine"] = ov["engine"]
    if "speed" in ov and ov["speed"]:
        tts["speed"] = ov["speed"]
    if "clone_preset_id" in ov and ov["clone_preset_id"]:  # AI Voice local clone voice preset
        tts["preset_id"] = ov["clone_preset_id"]
    if "auto_clean" in ov:
        options["auto_clean"] = ov["auto_clean"]
    if "auto_subtitle" in ov:
        options["auto_subtitle"] = ov["auto_subtitle"]
    return cfg


# --------------------------------------------------------------------------- #
#  Pipeline stages
# --------------------------------------------------------------------------- #
def _create_story_from_file(db, job: "models.BuildJob", cfg: Dict) -> "models.Story":
    """Read the file, split into chapters, persist, and set merged_content."""
    text = read_text_from_file(job.source_path)
    chapters = split_chapters(text)
    chapters = [c for c in chapters if (c.get("content") or "").strip()]
    if not chapters:
        raise RuntimeError("File không có nội dung để đọc")

    title = job.title or _nice_title(job.source_path)
    # batch_id groups this story under its batch in the history feed.
    story = models.Story(title=title, url="", start_chapter=1, end_chapter=1,
                         status="created", batch_id=job.batch_id)
    db.add(story)
    db.commit()
    db.refresh(story)

    for ch in chapters:
        content = ch.get("content") or ""
        db.add(models.Chapter(
            story_id=story.id,
            chapter_number=ch.get("chapter_number", 1),
            title=(ch.get("title") or None),
            content=content,
            char_count=len(content),
            status="pending",
        ))

    # merged_content = chapter bodies concatenated (headings excluded), matching
    # the wizard's /merged-content behavior. Persisted because the TTS processors
    # read story.merged_content directly.
    merged = "".join(c["content"].strip() for c in chapters)
    if (cfg.get("options") or {}).get("auto_clean"):
        merged = clean_story_text(merged)
    story.merged_content = merged
    story.status = "downloaded"
    story.current_step = 3  # a valid wizard step, so a failed job leaves a resumable draft
    db.commit()

    job.story_id = story.id
    db.commit()
    return story


def _run_tts_sync(db, story: "models.Story", tts: Dict) -> None:
    engine = (tts.get("engine") or "vbee").lower()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if engine == "ai_voice_local":
            from app.services.ai_voice_local_processor import AiVoiceLocalProcessor
            result = loop.run_until_complete(
                AiVoiceLocalProcessor(db=db).process_merged_content(
                    story_id=story.id, db=db, config=tts
                )
            )
        else:
            from app.services.tts_processor import VbeeTTSProcessor
            result = loop.run_until_complete(
                VbeeTTSProcessor(db=db).process_merged_content(
                    story_id=story.id,
                    db=db,
                    voice_code=tts.get("voice_code") or DEFAULT_VBEE_VOICE,
                    audio_type=tts.get("audio_type") or "mp3",
                    bitrate=tts.get("bitrate") or 128,
                    speed=tts.get("speed") or 1.0,
                )
            )
    finally:
        loop.close()
    if not result or not result.get("success"):
        raise RuntimeError((result or {}).get("error") or "TTS thất bại")


def _build_video_config(cfg: Dict, audio_path: str, banner: Optional[str],
                        subtitle: Optional[str] = None) -> Dict:
    """The preset stores video_cfg in backend format already (snake_case keys,
    stickers pre-converted), so we just overlay the per-story bits."""
    vcfg = dict(cfg.get("video_cfg") or {})
    # The preset bakes in a fixed clip_seed, so reusing it verbatim makes every
    # story in the batch shuffle its background clips into the SAME order. Give
    # each story a fresh seed so their clip sequences differ (only when shuffling;
    # "name" order stays deterministic A→Z by design).
    if vcfg.get("clip_order", "shuffle") == "shuffle":
        vcfg["clip_seed"] = random.randint(1, 1_000_000_000)
    pool = vcfg.get("transitions_pool") or [vcfg.get("transition_effect") or "crossfade"]
    vcfg.update({
        "video_source_folder": cfg.get("video_folder") or "",
        "audio_path": audio_path,
        "banner_image": banner,
        "bgm_path": cfg.get("bgm_path"),
        "watermark_image": cfg.get("watermark_image"),
        # subtitle_srt_path is stripped from the saved preset (it is per-story);
        # set it only when auto-subtitle produced an SRT for THIS story.
        "subtitle_srt_path": subtitle,
        "transitions_pool": pool,
        "transition_effect": random.choice(pool),
    })
    return vcfg


def _probe_audio_duration(path: str) -> float:
    """Seconds of an audio file via ffprobe, or 0 on any failure."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True,
        )
        if out.returncode == 0:
            return float(json.loads(out.stdout)["format"]["duration"])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[quick-build] ffprobe duration failed for {path}: {e}")
    return 0.0


def _make_subtitle(story: "models.Story", merged_audio: "models.MergedAudio") -> Optional[str]:
    """Generate an estimated SRT for the story's merged audio, returning its path
    (or None if it couldn't be built). Subtitle failure must never fail the job —
    the caller renders without subtitles instead."""
    try:
        text = (story.merged_content or "").strip()
        if not text:
            return None
        duration = merged_audio.duration or _probe_audio_duration(merged_audio.file_path)
        if not duration or duration <= 0:
            logger.warning(f"[quick-build] no audio duration for story {story.id}; skipping subtitles")
            return None
        out_path = str(paths.SRT_CACHE_DIR / f"quickbuild_{story.id}.srt")
        meta = build_estimated_srt(text, float(duration), out_path)
        if not meta.get("count"):
            return None
        logger.info(f"[quick-build] built {meta['count']} subtitle cues for story {story.id}")
        return meta["output_path"]
    except Exception as e:  # noqa: BLE001
        logger.error(f"[quick-build] subtitle generation failed for story {story.id}: {e}")
        return None


def _run_one_job(db, job: "models.BuildJob") -> None:
    from app.workers.video_worker import run_video_task

    cfg = _resolve_config(db, job)
    # Fail fast on a missing clip folder BEFORE running the multi-minute TTS —
    # otherwise the user waits out a full render only to hit a knowable error.
    if not cfg.get("video_folder"):
        raise RuntimeError("Preset chưa có folder clip nền")

    # --- create ---
    job.stage = "create"; job.status = "running"; job.error_message = None; db.commit()
    story = _create_story_from_file(db, job, cfg)

    # --- tts ---
    job.stage = "tts"; db.commit()
    _run_tts_sync(db, story, cfg["tts"])
    merged_audio = db.query(models.MergedAudio).filter(
        models.MergedAudio.story_id == story.id
    ).order_by(models.MergedAudio.created_at.desc()).first()
    if not merged_audio or not merged_audio.file_path or not os.path.exists(merged_audio.file_path):
        raise RuntimeError("TTS không tạo được file audio")
    story.current_step = 6  # TTS done — resumable at the Video step if render fails
    db.commit()

    # --- subtitle (optional, best-effort) ---
    subtitle = None
    if (cfg.get("options") or {}).get("auto_subtitle"):
        subtitle = _make_subtitle(story, merged_audio)

    # --- video ---
    job.stage = "video"; db.commit()
    vcfg = _build_video_config(cfg, merged_audio.file_path,
                               _auto_banner(job.source_path, cfg), subtitle)
    task = models.Task(story_id=story.id, type="video_processing", status="queued")
    db.add(task); db.commit(); db.refresh(task)
    result = run_video_task(task.id, story.id, vcfg)
    if not result or not result.get("success"):
        raise RuntimeError((result or {}).get("error") or "Render video thất bại")

    story.current_step = 8; story.status = "completed"; db.commit()
    job.output_path = result.get("output_path")
    job.stage = "done"; job.status = "done"; db.commit()


def _run_batch(batch_id: str) -> None:
    # The GPU guard was acquired synchronously by the endpoint before this thread
    # was spawned; we own it now and release it when the batch ends.
    db = SessionLocal()
    try:
        batch = db.query(models.BuildBatch).filter(models.BuildBatch.id == batch_id).first()
        if not batch:
            return
        batch.status = "running"; db.commit()

        jobs = db.query(models.BuildJob).filter(
            models.BuildJob.batch_id == batch_id
        ).order_by(models.BuildJob.order_index).all()

        for job in jobs:
            if not is_batch_running(batch_id):
                logger.info(f"[quick-build] batch {batch_id} stopped before job {job.order_index}")
                break
            # The user may have cancelled this still-queued job via /job/{id}/cancel
            # (a separate session marked it 'skipped'); reload and skip if so.
            db.refresh(job)
            if job.status != "pending":
                logger.info(f"[quick-build] skipping job {job.id} (status={job.status})")
                continue
            try:
                _run_one_job(db, job)
            except Exception as e:  # noqa: BLE001 — isolate per-file failures
                logger.error(f"[quick-build] job {job.id} ({job.source_path}) failed: {e}")
                _mark_job_error(db, job.id, str(e))

        stopped = not is_batch_running(batch_id)
        # No job may be left 'pending'/'running' — a stop skips the remaining
        # files, a crash mid-job leaves one 'running'; mark them so the UI shows
        # a final state (with a retry affordance) instead of a perpetual spinner.
        leftover = db.query(models.BuildJob).filter(
            models.BuildJob.batch_id == batch_id,
            models.BuildJob.status.in_(["pending", "running"]),
        ).all()
        for job in leftover:
            _mark_job_error(db, job.id, "Đã dừng batch" if stopped else "Không hoàn tất")

        batch = db.query(models.BuildBatch).filter(models.BuildBatch.id == batch_id).first()
        if batch:
            batch.status = "stopped" if stopped else "done"
            db.commit()
    finally:
        stop_batch(batch_id)
        gpu_guard.release()
        db.close()


def _mark_job_error(db, job_id: str, message: str) -> None:
    """Persist a job failure defensively — a bare rollback would otherwise leave
    the row stuck 'running' and spinning in the UI until the next app restart."""
    try:
        db.rollback()
        job = db.query(models.BuildJob).filter(models.BuildJob.id == job_id).first()
        if job:
            job.status = "error"
            job.error_message = message
            db.commit()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[quick-build] failed to mark job {job_id} error: {e}")
        db.rollback()


def recover_interrupted() -> None:
    """On startup, fail any job/batch left mid-run by a closed app — the thread
    driving them is gone, so they'd otherwise be stuck forever."""
    db = SessionLocal()
    try:
        # Batches that were queued/running have no live thread anymore.
        stuck_batches = db.query(models.BuildBatch).filter(
            models.BuildBatch.status.in_(["queued", "running"])
        ).all()
        stuck_ids = [b.id for b in stuck_batches]
        for batch in stuck_batches:
            batch.status = "stopped"
        # Their jobs — whether mid-run ('running') or never-started ('pending') —
        # would otherwise sit forever; mark them error so each gets a retry button.
        stuck_jobs = []
        if stuck_ids:
            stuck_jobs = db.query(models.BuildJob).filter(
                models.BuildJob.batch_id.in_(stuck_ids),
                models.BuildJob.status.in_(["running", "pending"]),
            ).all()
            for job in stuck_jobs:
                job.status = "error"
                job.error_message = "Bị gián đoạn (ứng dụng đã đóng khi đang chạy)"
        if stuck_batches or stuck_jobs:
            db.commit()
            logger.info(f"[quick-build] recovered {len(stuck_jobs)} job(s), {len(stuck_batches)} batch(es)")
    except Exception as e:  # noqa: BLE001
        logger.error(f"[quick-build] recover_interrupted failed: {e}")
        db.rollback()
    finally:
        db.close()
