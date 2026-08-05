"""
Per-segment TTS for AI Voice local.

Splits a story's merged content into short segments (by newline or by
sentence-ending punctuation), then generates / retries / merges them one at a
time. State lives in the ``tts_segments`` table so progress survives app
restarts.

Generation reuses ``AiVoiceLocalProcessor._generate_to_mp3`` (same clone/design
logic, same GPU model lock), so this module only owns splitting, file layout
and DB bookkeeping.
"""
import hashlib
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.services.output_delivery import get_output_folder, safe_file_stem

# Segments shorter than this get glued onto the previous one so period-splitting
# doesn't produce tiny fragments ("Vâng.", "Ừ.") that waste a whole generation.
_MIN_SEG_LEN = 8

# Sentence boundary: a . ! ? or … (incl. repeats like "?!" / "...") followed by
# whitespace or end of string. We keep the punctuation with the sentence.
_SENTENCE_RE = re.compile(r'[^.!?…]*[.!?…]+(?:\s+|$)|[^.!?…]+$')


def content_hash(text: Optional[str]) -> str:
    """SHA1 of the source content — used to detect the story changed since split."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def split_text(text: str, mode: str = "newline") -> List[str]:
    """Split story content into segments.

    mode="newline": one segment per non-empty line.
    mode="period":  one segment per sentence (., !, ?, …), tiny fragments glued
                    onto the previous sentence.
    """
    text = (text or "").strip()
    if not text:
        return []

    if mode == "newline":
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    # period mode — split per line first (keep author's paragraphing), then per
    # sentence within each line.
    raw: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for m in _SENTENCE_RE.finditer(line):
            piece = m.group().strip()
            if piece:
                raw.append(piece)

    # Glue fragments shorter than _MIN_SEG_LEN onto the previous segment.
    merged: List[str] = []
    for piece in raw:
        if merged and len(piece) < _MIN_SEG_LEN:
            merged[-1] = f"{merged[-1]} {piece}".strip()
        else:
            merged.append(piece)
    return merged


def story_folder_name(story: models.Story) -> str:
    """Filesystem-safe folder name for a story (mirrors ai_voice_local_processor)."""
    return (story.title or f"story_{story.id}").replace(' ', '_').replace('/', '_')


def story_output_name(story: models.Story) -> str:
    """Delivery sub-folder name for a story — MUST match the ``subfolder`` that
    ``deliver_final`` uses in :func:`merge_segments`, so the per-segment files and
    the finished product land in the same ``<output>/<story>/`` directory."""
    return safe_file_stem(story.title if story.title else story.id, story.id)


def _next_ai_voice_local_seq(folder: Path, stem: str) -> int:
    """Next sequence number for an AI Voice local product in ``folder``.

    Scans for existing ``ai_voice_local_<n>_<stem>.mp3`` files and returns max+1
    (1 if none). This gives each merge a distinct, ordered name so re-merges
    don't overwrite each other and AI Voice local output is told apart from VBEE's.
    """
    if not folder.exists():
        return 1
    pat = re.compile(rf"^ai_voice_local_(\d+)_{re.escape(stem)}\.mp3$", re.IGNORECASE)
    mx = 0
    for p in folder.iterdir():
        m = pat.match(p.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


def segments_dir(story: models.Story, db: Session) -> Path:
    """Where per-sentence mp3s live: ``<output folder>/<story>/segments/``.

    This sits inside the user's delivery folder (Downloads by default) — the same
    folder the merged product is delivered to — so opening it shows both the short
    per-sentence files and the final ``<story>.mp3`` side by side.
    """
    return get_output_folder(db) / story_output_name(story) / "segments"


def _delete_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
    except OSError as e:
        logger.warning(f"[segment-tts] could not delete {path}: {e}")


def clear_segments(db: Session, story_id: str) -> int:
    """Delete all segments (and their mp3 files) for a story. Returns count removed."""
    segs = db.query(models.TtsSegment).filter(
        models.TtsSegment.story_id == story_id
    ).all()
    for seg in segs:
        _delete_file(seg.file_path)
    n = len(segs)
    db.query(models.TtsSegment).filter(
        models.TtsSegment.story_id == story_id
    ).delete(synchronize_session=False)
    db.commit()
    return n


def create_segments(db: Session, story: models.Story, mode: str, config: Dict) -> List[models.TtsSegment]:
    """Split ``story.merged_content`` and (re)create the segment rows.

    Any existing segments for the story are removed first (caller decides when
    it is safe to do so — e.g. after confirming the source changed).
    """
    clear_segments(db, story.id)

    lines = split_text(story.merged_content or "", mode)
    src_hash = content_hash(story.merged_content)
    segs: List[models.TtsSegment] = []
    for i, line in enumerate(lines, start=1):
        seg = models.TtsSegment(
            story_id=story.id,
            seg_index=i,
            text=line,
            status="pending",
            split_mode=mode,
            source_hash=src_hash,
            config=config,
        )
        db.add(seg)
        segs.append(seg)
    db.commit()
    for seg in segs:
        db.refresh(seg)
    logger.info(f"[segment-tts] story {story.id}: split into {len(segs)} segments (mode={mode})")
    return segs


def source_changed(db: Session, story: models.Story) -> bool:
    """True if the story's merged_content differs from what segments were split from."""
    first = db.query(models.TtsSegment).filter(
        models.TtsSegment.story_id == story.id
    ).order_by(models.TtsSegment.seg_index).first()
    if not first:
        return False
    return first.source_hash != content_hash(story.merged_content)


def synthesize_segment(db: Session, seg: models.TtsSegment) -> Dict:
    """Generate mp3 for one segment. Updates the row in place. Returns result dict."""
    from app.services.ai_voice_local_processor import AiVoiceLocalProcessor

    story = db.query(models.Story).filter(models.Story.id == seg.story_id).first()
    if not story:
        return {"success": False, "error": "Story not found"}

    out_dir = segments_dir(story, db)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"seg_{seg.seg_index:04d}.mp3"

    seg.status = "processing"
    seg.error_message = None
    seg.attempts = (seg.attempts or 0) + 1
    db.commit()

    try:
        import time as _time
        t0 = _time.time()
        # Reuse AI Voice local's single-text mp3 generator (handles clone/design + GPU lock).
        duration = AiVoiceLocalProcessor(db=db)._generate_to_mp3(
            seg.text, seg.config or {}, out_path
        )
        seg.file_path = str(out_path)
        seg.file_size = os.path.getsize(out_path) if out_path.exists() else None
        seg.duration = duration
        seg.gen_sec = _time.time() - t0
        seg.status = "done"
        seg.error_message = None
        db.commit()
        return {"success": True, "duration": duration}
    except Exception as e:  # noqa: BLE001 - surface any generation failure to the row
        logger.error(f"[segment-tts] seg #{seg.seg_index} ({seg.id}) failed: {e}")
        _delete_file(str(out_path))
        seg.file_path = None
        seg.status = "error"
        seg.error_message = str(e)
        db.commit()
        return {"success": False, "error": str(e)}


def merge_segments(db: Session, story: models.Story) -> Dict:
    """Concatenate all done segments (in order) into one final mp3.

    Requires every segment to be 'done'. Reuses ffmpeg concat + deliver_final so
    the output lands in the user's Downloads sub-folder like the one-shot path.
    """
    import subprocess
    from app.services.output_delivery import deliver_final

    segs = db.query(models.TtsSegment).filter(
        models.TtsSegment.story_id == story.id
    ).order_by(models.TtsSegment.seg_index).all()
    if not segs:
        return {"success": False, "error": "Chưa có câu nào để ghép."}
    not_done = [s for s in segs if s.status != "done" or not s.file_path]
    if not_done:
        return {"success": False,
                "error": f"Còn {len(not_done)} câu chưa xong — hãy chạy/retry hết trước khi ghép."}

    out_dir = Path(settings.STORAGE_PATH) / "audio" / story_folder_name(story)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "merged_audio.mp3"
    list_file = out_dir / "segments_concat.txt"

    bitrate = int((segs[0].config or {}).get("bitrate", 128))

    # ffmpeg concat demuxer needs a list file of absolute, forward-slash paths.
    with open(list_file, "w", encoding="utf-8") as f:
        for s in segs:
            p = os.path.abspath(s.file_path).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{p}'\n")

    try:
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c:a", "libmp3lame", "-b:a", f"{bitrate}k",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=1800)
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="ignore")[-300:] if proc.stderr else "unknown"
            return {"success": False, "error": f"ffmpeg concat failed: {err}"}
    finally:
        try:
            list_file.unlink(missing_ok=True)
        except OSError:
            pass

    file_size = os.path.getsize(out_path)
    total_duration = sum((s.duration or 0.0) for s in segs)

    # Prefix the product with the engine + a running number so it's told apart
    # from any VBEE file and successive re-merges don't clobber each other.
    name = story_output_name(story)
    seq = _next_ai_voice_local_seq(get_output_folder(db) / name, name)
    final_path = deliver_final(str(out_path), db, filename=f"ai_voice_local_{seq}_{name}.mp3", subfolder=name)

    merged = db.query(models.MergedAudio).filter(
        models.MergedAudio.story_id == story.id
    ).first()
    if merged:
        merged.file_path = final_path
        merged.file_size = file_size
        merged.duration = total_duration
        merged.format = "mp3"
        merged.total_chapters = len(segs)
        merged.engine = "ai_voice_local"
    else:
        merged = models.MergedAudio(
            story_id=story.id, file_path=final_path, file_size=file_size,
            duration=total_duration, format="mp3", total_chapters=len(segs),
            engine="ai_voice_local",
        )
        db.add(merged)
    db.commit()

    logger.info(f"[segment-tts] merged {len(segs)} segments -> {final_path} ({total_duration:.1f}s)")
    return {"success": True, "file_path": final_path, "file_size": file_size,
            "duration": total_duration, "segment_count": len(segs)}


def segment_stats(db: Session, story_id: str) -> Dict:
    """Counts by status for a story's segments (grouped COUNT — never loads text)."""
    from sqlalchemy import func as safunc

    rows = db.query(
        models.TtsSegment.status, safunc.count(models.TtsSegment.id)
    ).filter(
        models.TtsSegment.story_id == story_id
    ).group_by(models.TtsSegment.status).all()

    by = {"pending": 0, "processing": 0, "done": 0, "error": 0}
    total = 0
    for status, count in rows:
        by[status] = count
        total += count
    return {
        "total": total,
        "pending": by["pending"],
        "processing": by["processing"],
        "done": by["done"],
        "error": by["error"],
        "all_done": total > 0 and by["done"] == total,
    }
