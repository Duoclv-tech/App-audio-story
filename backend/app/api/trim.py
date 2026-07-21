"""
Video Trim API endpoints
"""
import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel

from app import paths
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
    output_filename: str = "output.mp4"


class TrimProcessResponse(BaseModel):
    job_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=TrimUploadResponse)
async def upload_video(file: UploadFile = File(...)):
    """Accept a video upload, persist it to trim_temp, return metadata."""
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


@router.post("/clear/{file_id}")
async def clear_temp(file_id: str):
    """Delete the temp folder for a file_id."""
    dest_dir = TRIM_TEMP_DIR / file_id
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    return {"cleared": True}


@router.get("/video/{file_id}")
async def serve_input_video(file_id: str):
    """Serve the uploaded source video (for preview restore after page reload)."""
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
