"""
Video Trim API endpoints
"""
import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel

from app import paths
from app.api.video import _reveal_in_file_manager, require_localhost
from app.database import SessionLocal
from app.services.output_delivery import deliver_final, get_output_folder
from app.services.video_trimmer import (
    TRIM_TEMP_DIR,
    probe,
    generate_waveform,
    trim,
)

router = APIRouter()

# Upload size ceiling (matches the 2 GB documented limit) so a stray/hostile
# upload can't fill the disk.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

# trim_temp holds large uploaded/imported videos. They're only removed when the
# client calls /clear, which never happens if the tab is closed/reloaded/errors
# out. Sweep dirs older than this on each new upload/import so they can't pile
# up unbounded (mirrors the preview/SRT cache sweeps).
_TRIM_TTL_SECONDS = 6 * 3600


def _sweep_trim_temp() -> None:
    """Delete trim_temp subdirs older than the TTL. A dir being actively used
    has a fresh mtime, so an in-flight job is never swept."""
    now = time.time()
    try:
        if not TRIM_TEMP_DIR.exists():
            return
        for d in TRIM_TEMP_DIR.iterdir():
            try:
                if d.is_dir() and now - d.stat().st_mtime > _TRIM_TTL_SECONDS:
                    shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[trim] temp sweep failed: {e}")


def _assert_import_allowed(src: Path) -> None:
    """Confine /import to files the app itself produced.

    Without this, ``path`` is an arbitrary absolute path → any file on disk
    could be copied into trim_temp and downloaded back out. Allowed roots are
    the app storage tree and the user's configured output folder.
    """
    allowed = [Path(paths.STORAGE_DIR).resolve(), Path(paths.DATA_DIR).resolve()]
    db = SessionLocal()
    try:
        allowed.append(get_output_folder(db).resolve())
    except Exception:
        pass
    finally:
        db.close()
    try:
        real = src.resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not any(real == root or root in real.parents for root in allowed):
        raise HTTPException(status_code=403, detail="Path is outside allowed folders")

# ---------------------------------------------------------------------------
# In-memory job registry
# ---------------------------------------------------------------------------

class _JobState:
    def __init__(self):
        self.percent: float = 0.0
        self.status: str = "running"  # "running" | "completed" | "failed"
        self.error: Optional[str] = None
        self.output_path: Optional[str] = None
        self.input_file_id: Optional[str] = None

_jobs: dict[str, _JobState] = {}

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TrimUploadResponse(BaseModel):
    file_id: str
    duration: float
    width: int
    height: int
    video_codec: str
    audio_codec: Optional[str]
    original_filename: str


class AspectRatioParams(BaseModel):
    mode: str = "original"
    custom_w: Optional[int] = None
    custom_h: Optional[int] = None


class WatermarkParams(BaseModel):
    enabled: bool = False
    text: str = ""
    font_size: int = 36
    color: str = "#FFFFFF"
    opacity: float = 0.85
    position: str = "bottom-center"
    custom_x: float = 0.5
    custom_y: float = 0.5
    margin: int = 20
    rotation: int = 0
    border_enabled: bool = True
    border_color: str = "#000000"
    border_width: int = 2


class SegmentParams(BaseModel):
    start_sec: float
    end_sec: float


class SubtitleParams(BaseModel):
    """Burn a (re-based) SRT onto the trimmed clip. `srt_path` points at the
    file saved by /trim/upload-srt. Style mirrors the main pipeline's subtitle
    config (subtitle_renderer.SubtitleStyle)."""
    enabled: bool = False
    srt_path: Optional[str] = None
    animation: str = "fade"
    font: str = "Be Vietnam Pro (Vietnamese)"
    font_size: int = 56
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 3
    shadow: int = 0
    bold: bool = True
    italic: bool = False
    align: str = "center"
    x: float = 0.5
    y: float = 0.85
    opacity: float = 1.0
    max_width: float = 0.9


class TrimProcessRequest(BaseModel):
    file_id: str
    segments: list[SegmentParams]
    quality: str = "original"
    custom_bitrate_kbps: Optional[int] = None
    aspect_ratio: AspectRatioParams = AspectRatioParams()
    crop_mode: str = "crop"
    mute: bool = False
    volume: float = 1.0
    speed: float = 1.0
    exact_frame: bool = True
    fade: bool = False
    watermark: WatermarkParams = WatermarkParams()
    subtitle: SubtitleParams = SubtitleParams()
    output_filename: str = "output.mp4"


class TrimProcessResponse(BaseModel):
    job_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=TrimUploadResponse)
async def upload_video(file: UploadFile = File(...)):
    """Accept a video upload, persist it to trim_temp, return metadata."""
    _sweep_trim_temp()
    file_id = str(uuid.uuid4())
    dest_dir = TRIM_TEMP_DIR / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "input.mp4").suffix or ".mp4"
    input_path = dest_dir / f"input{suffix}"

    chunk_size = 1024 * 1024  # 1 MB
    total = 0
    try:
        with open(input_path, "wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024**3)} GB)",
                    )
                f.write(chunk)
    except Exception:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    try:
        meta = probe(str(input_path))
    except Exception as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Cannot probe video: {e}")

    return TrimUploadResponse(
        file_id=file_id,
        duration=meta["duration"],
        width=meta["width"],
        height=meta["height"],
        video_codec=meta["video_codec"],
        audio_codec=meta.get("audio_codec"),
        original_filename=file.filename or "input.mp4",
    )


class TrimImportRequest(BaseModel):
    path: str


@router.post("/import", response_model=TrimUploadResponse)
async def import_video(request: TrimImportRequest):
    """Register an existing server-side video file into trim_temp (no re-upload).

    Used to feed the long video produced by the pipeline directly into the
    trimmer to cut a short clip for Shorts/TikTok.
    """
    _sweep_trim_temp()
    src = Path(request.path)
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {request.path}")
    _assert_import_allowed(src)

    file_id = str(uuid.uuid4())
    dest_dir = TRIM_TEMP_DIR / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = src.suffix or ".mp4"
    input_path = dest_dir / f"input{suffix}"

    try:
        # Hardlink is instant and space-free on the same volume; fall back to a
        # copy across volumes or when the filesystem disallows it.
        try:
            os.link(str(src), str(input_path))
        except OSError:
            shutil.copy2(str(src), str(input_path))
    except Exception as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Cannot import file: {e}")

    try:
        meta = probe(str(input_path))
    except Exception as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Cannot probe video: {e}")

    return TrimUploadResponse(
        file_id=file_id,
        duration=meta["duration"],
        width=meta["width"],
        height=meta["height"],
        video_codec=meta["video_codec"],
        audio_codec=meta.get("audio_codec"),
        original_filename=src.name,
    )


class TrimFromFolderRequest(BaseModel):
    folder: str
    # Target duration to fill — the original imported video's length. Random
    # clips from the folder are concatenated and trimmed to exactly this.
    target_duration: float
    # Output frame size — defaults mirror the original video so the generated
    # clip drops in as a replacement of the same resolution.
    width: int = 1920
    height: int = 1080
    clip_order: str = "shuffle"  # "shuffle" (random) | "name" (A→Z)
    clip_seed: Optional[int] = None
    # Mute the folder clips' audio (default on). Only affects the visual clips
    # pulled from the folder, not the original imported video's audio.
    mute_audio: bool = True
    # file_id of the currently-loaded video whose audio should be muxed onto the
    # generated background (so the folder clips become pure visuals while the
    # original narration/voice is preserved). None => no original audio to keep.
    original_file_id: Optional[str] = None
    # When False (default) the original imported video's audio is muxed onto the
    # generated background. When True the output is left with only the folder
    # clips' audio (or silent if those are muted too).
    mute_original_audio: bool = False


@router.post("/from-folder", response_model=TrimUploadResponse)
async def trim_from_folder(request: TrimFromFolderRequest):
    """Build a trim source by randomly concatenating clips from a folder.

    Mirrors the ProcessorPage "Video Source Folder" logic: scan the folder,
    order shuffle/name (seeded), accumulate clips (looping the list when the
    folder is shorter than the target) until the total reaches
    ``target_duration``, concat, then trim the tail to that exact length. The
    result is registered into trim_temp like a normal upload so the rest of the
    trim flow (preview, segments, watermark, export) works unchanged.
    """
    _sweep_trim_temp()

    from app.services.video_processor import VideoProcessor

    folder = (request.folder or "").strip()
    if request.target_duration <= 0:
        raise HTTPException(status_code=400, detail="target_duration must be > 0")

    svc = VideoProcessor()
    order = "name" if request.clip_order == "name" else "shuffle"
    videos, error = svc.scan_video_folder(folder, order=order, seed=request.clip_seed)
    if error:
        raise HTTPException(status_code=422, detail=error)

    # Accumulate clips (looping the list if the folder is short) until we cover
    # the target duration; the concat is trimmed to the exact length below. Log
    # if the backstop cap leaves a shortfall so it's never silent.
    selected, total = svc.select_clips_for_duration(videos, request.target_duration)
    if total < request.target_duration:
        logger.warning(
            f"[trim] folder too short to fill {request.target_duration:.1f}s "
            f"(got {total:.1f}s from {len(selected)} clips)"
        )

    file_id = str(uuid.uuid4())
    dest_dir = TRIM_TEMP_DIR / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    input_path = str(dest_dir / "input.mp4")

    # Repeated same-path inputs (when the list loops) are fine for ffmpeg, so we
    # pass source paths directly instead of copying every clip to a temp folder.
    clip_paths = [v["path"] for v in selected]
    # H.264 / yuv420p needs even dimensions; the source video may report an odd
    # width/height, so round each down to the nearest even value.
    out_w = max(2, (request.width // 2) * 2)
    out_h = max(2, (request.height // 2) * 2)
    resolution = f"{out_w}x{out_h}"

    def _build():
        return svc.concatenate_videos_from_folder(
            clip_paths,
            input_path,
            resolution=resolution,
            keep_audio=not request.mute_audio,
            max_duration=request.target_duration,
        )

    try:
        result = await asyncio.get_event_loop().run_in_executor(None, _build)
    except Exception as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        logger.exception("from-folder concat failed")
        raise HTTPException(status_code=500, detail=f"Concat failed: {e}")

    if not result.get("success"):
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=result.get("error", "Concat failed"))

    # Preserve the original imported video's audio: the folder clips are only a
    # visual background, so unless the user opted to mute it, mux the original
    # audio onto the freshly-concatenated video. When the folder clips kept their
    # own audio (mute_audio=False) both tracks are mixed; otherwise the original
    # audio simply replaces the (silent) folder track.
    if not request.mute_original_audio and request.original_file_id:
        orig_dir = TRIM_TEMP_DIR / request.original_file_id
        # The source may have been imported with any container extension, so
        # resolve the actual input.* file rather than assuming .mp4.
        orig_matches = sorted(orig_dir.glob("input.*")) if orig_dir.exists() else []
        orig_path = orig_matches[0] if orig_matches else None
        try:
            orig_has_audio = bool(orig_path and probe(str(orig_path)).get("audio_codec"))
        except Exception:
            orig_has_audio = False
        if orig_has_audio:
            try:
                concat_has_audio = bool(probe(input_path).get("audio_codec"))
            except Exception:
                concat_has_audio = False
            muxed = str(dest_dir / "muxed.mp4")
            if concat_has_audio:
                # Both the folder background and the original video carry audio —
                # mix them, capping to the (background) video length.
                mux_cmd = [
                    "ffmpeg", "-y", "-i", input_path, "-i", str(orig_path),
                    "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[aout]",
                    "-map", "0:v:0", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                    muxed,
                ]
            else:
                # Background is silent — carry over the original audio as-is.
                mux_cmd = [
                    "ffmpeg", "-y", "-i", input_path, "-i", str(orig_path),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                    muxed,
                ]
            proc = subprocess.run(mux_cmd, capture_output=True, text=True)
            if proc.returncode == 0 and os.path.exists(muxed):
                os.replace(muxed, input_path)
            else:
                logger.warning(
                    f"[trim] mux original audio failed (keeping muted background): "
                    f"{proc.stderr[-500:] if proc.stderr else 'unknown error'}"
                )

    try:
        meta = probe(input_path)
    except Exception as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Cannot probe generated video: {e}")

    return TrimUploadResponse(
        file_id=file_id,
        duration=meta["duration"],
        width=meta["width"],
        height=meta["height"],
        video_codec=meta["video_codec"],
        audio_codec=meta.get("audio_codec"),
        original_filename=f"folder_{Path(folder).name}.mp4",
    )


@router.get("/waveform/{file_id}")
async def get_waveform(file_id: str):
    """Return audio waveform as JSON array of floats [0..1]."""
    dest_dir = TRIM_TEMP_DIR / file_id
    if not dest_dir.exists():
        raise HTTPException(status_code=404, detail="file_id not found")

    inputs = list(dest_dir.glob("input.*"))
    if not inputs:
        raise HTTPException(status_code=404, detail="Input file missing")

    try:
        peaks = generate_waveform(str(inputs[0]))
    except Exception as e:
        logger.error(f"Waveform generation failed: {e}")
        peaks = [0.0] * 500

    return {"waveform": peaks}


@router.post("/upload-srt")
async def upload_trim_srt(file_id: str = Form(...), file: UploadFile = File(...)):
    """Save an SRT alongside a trim video (trim_temp/<file_id>/subtitle.srt).

    Standalone counterpart to /video/upload-srt (which is scoped to a story) so
    the Cắt video tab can attach subtitles without a story_id. Returns parse
    metadata for the panel to show line count / span.
    """
    # file_id is normally a server-issued uuid; reject anything with path
    # separators or traversal so a hostile value can't escape trim_temp and
    # clobber a subtitle.srt elsewhere on disk.
    if not file_id or any(c in file_id for c in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="invalid file_id")

    dest_dir = TRIM_TEMP_DIR / file_id
    if not dest_dir.exists():
        raise HTTPException(status_code=404, detail="file_id not found")

    fname = file.filename or "subtitle.srt"
    if not fname.lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail="Only .srt files are accepted")

    dest = dest_dir / "subtitle.srt"
    chunk_size = 256 * 1024
    written = 0
    max_bytes = 5 * 1024 * 1024  # 5 MB hard cap — SRTs are tiny
    try:
        with open(dest, "wb") as f_out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    f_out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="SRT file too large (max 5MB)")
                f_out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Cannot save SRT: {e}")

    from app.services import subtitle_renderer
    try:
        meta = subtitle_renderer.probe_srt(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Cannot parse SRT: {e}")

    return {
        "srt_path": str(dest),
        "filename": fname,
        "segment_count": meta["segment_count"],
        "first_start": meta["first_start"],
        "last_end": meta["last_end"],
    }


@router.post("/process", response_model=TrimProcessResponse)
async def process_trim(request: TrimProcessRequest):
    """Start an async trim job. Returns job_id for SSE polling."""
    dest_dir = TRIM_TEMP_DIR / request.file_id
    if not dest_dir.exists():
        raise HTTPException(status_code=404, detail="file_id not found")

    inputs = list(dest_dir.glob("input.*"))
    if not inputs:
        raise HTTPException(status_code=404, detail="Input file missing")

    input_path = str(inputs[0])

    # Sanitize output filename
    safe_name = Path(request.output_filename).name
    if not safe_name.endswith(".mp4"):
        safe_name = safe_name + ".mp4"
    output_path = str(dest_dir / safe_name)

    job_id = str(uuid.uuid4())
    job = _JobState()
    job.input_file_id = request.file_id
    job.output_path = output_path
    _jobs[job_id] = job

    params = request.model_dump()

    async def _run():
        loop = asyncio.get_event_loop()
        try:
            def _sync_trim():
                def cb(pct):
                    job.percent = pct

                return trim(input_path, output_path, params, progress_cb=cb)

            result = await loop.run_in_executor(None, _sync_trim)
            if result.get("success"):
                # Deliver the trimmed short clip to the user's output folder
                # (Downloads by default). The download endpoint serves
                # job.output_path, so it keeps working from the new location.
                _db = SessionLocal()
                try:
                    job.output_path = deliver_final(output_path, _db, filename=safe_name)
                finally:
                    _db.close()
                job.status = "completed"
                job.percent = 100.0
            else:
                job.status = "failed"
                job.error = result.get("error", "Unknown error")
        except Exception as e:
            logger.exception("Trim job failed")
            job.status = "failed"
            job.error = str(e)

    asyncio.create_task(_run())

    return TrimProcessResponse(job_id=job_id)


@router.get("/progress/{job_id}")
async def stream_progress(job_id: str):
    """SSE stream: yields {percent, status} every 500 ms."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="job_id not found")

    async def _event_generator():
        job = _jobs[job_id]
        while True:
            payload: dict = {
                "percent": round(job.percent, 1),
                "status": job.status,
            }
            if job.error:
                payload["error"] = job.error
            if job.status == "completed" and job.output_path:
                payload["output_path"] = job.output_path
            yield f"data: {json.dumps(payload)}\n\n"

            if job.status != "running":
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/download/{job_id}")
async def download_output(job_id: str):
    """Serve the trimmed MP4 file as a download."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="job_id not found")

    job = _jobs[job_id]
    if job.status != "completed":
        raise HTTPException(status_code=400, detail=f"Job not completed (status={job.status})")

    if not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    filename = Path(job.output_path).name
    return FileResponse(
        path=job.output_path,
        media_type="video/mp4",
        filename=filename,
    )


@router.post("/reveal/{job_id}")
async def reveal_output(job_id: str, _: None = Depends(require_localhost)):
    """Open the OS file manager with the trimmed file selected.

    The desktop app already saves the finished MP4 to the user's output folder,
    so "download" is really "show me where it is" — and WebView2 can't trigger a
    programmatic blob download anyway. Reveal the file selected in Explorer.

    Gated to localhost like the other reveal endpoints: it spawns an Explorer
    subprocess on the host, which must not be reachable if API_HOST=0.0.0.0.
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="job_id not found")

    job = _jobs[job_id]
    if job.status != "completed":
        raise HTTPException(status_code=400, detail=f"Job not completed (status={job.status})")

    if not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(status_code=404, detail="File đã bị xóa hoặc di chuyển khỏi máy.")

    path = os.path.normpath(job.output_path)
    try:
        _reveal_in_file_manager(path)
    except Exception as e:
        logger.error(f"[trim] reveal output failed: {e}")
        raise HTTPException(status_code=500, detail="Không mở được thư mục chứa file.")
    return {"revealed": path}


@router.post("/clear/{file_id}")
async def clear_temp(file_id: str):
    """Delete the temp folder for a file_id."""
    dest_dir = TRIM_TEMP_DIR / file_id
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    return {"cleared": True}


@router.api_route("/video/{file_id}", methods=["GET", "HEAD"])
async def serve_input_video(file_id: str):
    """Serve the uploaded source video (for preview restore after page reload).

    HEAD is included so the frontend's checkFileExists() (a HEAD probe) can
    confirm a persisted file_id still exists; without it the probe 405s and the
    trimmer wrongly wipes restored state on every reload.
    """
    dest_dir = TRIM_TEMP_DIR / file_id
    if not dest_dir.exists():
        raise HTTPException(status_code=404, detail="file_id not found")
    inputs = list(dest_dir.glob("input.*"))
    if not inputs:
        raise HTTPException(status_code=404, detail="Input file missing")
    input_path = inputs[0]
    media_type = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".webm": "video/webm",
    }.get(input_path.suffix.lower(), "application/octet-stream")
    return FileResponse(path=str(input_path), media_type=media_type)
