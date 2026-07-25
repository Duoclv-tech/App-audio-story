"""
Video Processing API endpoints
"""
import hashlib
import json
import os
import string
import threading
import time
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from loguru import logger

from app.database import get_db
from app import models, schemas, paths
from app.services.video_processor import VideoProcessor
from app.services.fonts import list_fonts, ensure_font, get_font_file_path
from app.workers.video_worker import run_video_task

router = APIRouter()

# Loopback addresses allowed to hit the filesystem-browse / arbitrary-path
# preview endpoints below.
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def require_localhost(request: Request) -> None:
    """Gate an endpoint to same-machine callers.

    The browse/preview endpoints accept absolute filesystem paths and serve any
    file on disk — safe as the desktop app's native file picker (bound to
    127.0.0.1), but a full arbitrary-file-read hole the moment the server is
    reachable on the LAN (e.g. someone sets API_HOST=0.0.0.0). This makes the
    localhost restriction explicit regardless of the bind address.
    """
    host = request.client.host if request.client else None
    if host not in _LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="Localhost-only endpoint")

_PREVIEW_JOBS: dict = {}
_PREVIEW_LOCK = threading.Lock()
_PREVIEW_CACHE_DIR = paths.PREVIEW_CACHE_DIR
_PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_PREVIEW_TTL_SECONDS = 3600

_AD_FIELDS = (
    "ad_flip_random", "ad_flip_all",
    "ad_zoom", "ad_zoom_factor",
    "ad_color", "ad_saturation", "ad_contrast", "ad_gamma", "ad_hue_shift",
    "ad_clip_speed_jitter", "ad_clip_speed_jitter_range",
    "ad_strip_metadata",
)

_VIZ_FIELDS = (
    "visualizer_enabled", "visualizer_style",
    "visualizer_x", "visualizer_y", "visualizer_w", "visualizer_h",
    "visualizer_color1", "visualizer_color2", "visualizer_opacity",
    "visualizer_bg_mode", "visualizer_bg_color", "visualizer_bg_opacity",
    "visualizer_spectrum_preset",
    "visualizer_bars_mode", "visualizer_waveform_mode", "visualizer_waveform_mirror",
)


def _extract_ad_options(request: schemas.VideoProcessRequest) -> dict:
    return {f: getattr(request, f) for f in _AD_FIELDS}


def _extract_viz_options(request: schemas.VideoProcessRequest) -> dict:
    return {f: getattr(request, f) for f in _VIZ_FIELDS}


@router.post("/start", response_model=schemas.VideoProcessResponse)
async def start_video_processing(
    request: schemas.VideoProcessRequest,
    db: Session = Depends(get_db)
):
    """Start video processing as a background task"""
    # Check story exists
    story = db.query(models.Story).filter(models.Story.id == request.story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Check audio source: custom path or merged audio from DB
    if request.audio_path:
        if not os.path.exists(request.audio_path):
            raise HTTPException(status_code=400, detail=f"Audio file not found: {request.audio_path}")
    else:
        merged_audio = db.query(models.MergedAudio).filter(
            models.MergedAudio.story_id == request.story_id
        ).first()
        if not merged_audio:
            raise HTTPException(status_code=400, detail="No merged audio found. Please complete audio merge first or provide a custom audio path.")

    # Validate video folder
    processor = VideoProcessor()
    validation = processor.validate_video_folder(request.video_source_folder)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation.get("error", "Invalid video folder"))

    # Create task
    task = models.Task(
        story_id=request.story_id,
        type="video_processing",
        status="queued"
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Run in background thread
    import random
    pool = request.transitions_pool or [request.transition_effect]
    config = {
        "video_source_folder": request.video_source_folder,
        "audio_path": request.audio_path,
        "audio_speed": request.audio_speed,
        "transition_effect": random.choice(pool),
        "transitions_pool": pool,
        "transition_duration": request.transition_duration,
        "resolution": request.resolution,
        "banner_image": request.banner_image,
        "banner_video_scale": request.banner_video_scale,
        "banner_video_offset_x": request.banner_video_offset_x,
        "banner_video_offset_y": request.banner_video_offset_y,
        "banner_video_scale_x": request.banner_video_scale_x,
        "banner_video_scale_y": request.banner_video_scale_y,
        "overlay_opacity": request.overlay_opacity,
        "watermark_image": request.watermark_image,
        "watermark_x": request.watermark_x,
        "watermark_y": request.watermark_y,
        "watermark_w": request.watermark_w,
        "watermark_h": request.watermark_h,
        "watermark_shape": request.watermark_shape,
        "watermark_opacity": request.watermark_opacity,
        "watermark_text": request.watermark_text,
        "watermark_text_font": request.watermark_text_font,
        "watermark_text_size": request.watermark_text_size,
        "watermark_text_color": request.watermark_text_color,
        "watermark_text_angle": request.watermark_text_angle,
        "watermark_text_x": request.watermark_text_x,
        "watermark_text_y": request.watermark_text_y,
        "watermark_text_opacity": request.watermark_text_opacity,
        "subtitle_srt_path": request.subtitle_srt_path,
        "subtitle_animation": request.subtitle_animation,
        "subtitle_font": request.subtitle_font,
        "subtitle_font_size": request.subtitle_font_size,
        "subtitle_color": request.subtitle_color,
        "subtitle_outline_color": request.subtitle_outline_color,
        "subtitle_outline_width": request.subtitle_outline_width,
        "subtitle_shadow": request.subtitle_shadow,
        "subtitle_bold": request.subtitle_bold,
        "subtitle_italic": request.subtitle_italic,
        "subtitle_align": request.subtitle_align,
        "subtitle_x": request.subtitle_x,
        "subtitle_y": request.subtitle_y,
        "subtitle_opacity": request.subtitle_opacity,
        "fade_in": request.fade_in,
        "fade_out": request.fade_out,
        "mute_source_videos": request.mute_source_videos,
        "stickers": [s.model_dump() for s in (request.stickers or [])],
        **_extract_ad_options(request),
        **_extract_viz_options(request),
    }

    thread = threading.Thread(
        target=run_video_task,
        args=(task.id, request.story_id, config),
        daemon=True
    )
    thread.start()

    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Video processing started"
    }


@router.get("/{task_id}/status", response_model=schemas.TaskResponse)
async def get_video_task_status(task_id: str, db: Session = Depends(get_db)):
    """Get video processing task status"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/result/{story_id}", response_model=schemas.VideoOutputResponse)
async def get_video_result(story_id: str, db: Session = Depends(get_db)):
    """Get video processing result for a story"""
    video_output = db.query(models.VideoOutput).filter(
        models.VideoOutput.story_id == story_id
    ).order_by(models.VideoOutput.created_at.desc()).first()

    if not video_output:
        raise HTTPException(status_code=404, detail="No video output found for this story")

    return video_output


@router.get("/audio-path/{story_id}")
async def get_audio_path(story_id: str, db: Session = Depends(get_db)):
    """Get merged audio path for a story (for auto-fill in video step)"""
    merged_audio = db.query(models.MergedAudio).filter(
        models.MergedAudio.story_id == story_id
    ).order_by(models.MergedAudio.created_at.desc()).first()

    if merged_audio and merged_audio.file_path and os.path.exists(merged_audio.file_path):
        return {"audio_path": merged_audio.file_path, "found": True}

    return {"audio_path": None, "found": False}


def _safe_filename(name: str, fallback: str) -> str:
    """Strip characters Windows/most OSes reject in a filename."""
    cleaned = "".join(c for c in (name or "") if c not in '\\/:*?"<>|').strip()
    return cleaned or fallback


@router.get("/download-audio/{story_id}")
async def download_merged_audio(story_id: str, db: Session = Depends(get_db)):
    """Serve the finished merged audio as a downloadable attachment (final deliverable)."""
    merged_audio = db.query(models.MergedAudio).filter(
        models.MergedAudio.story_id == story_id
    ).order_by(models.MergedAudio.created_at.desc()).first()

    if not merged_audio or not merged_audio.file_path or not os.path.exists(merged_audio.file_path):
        raise HTTPException(status_code=404, detail="Chưa có audio hoàn chỉnh cho truyện này.")

    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    ext = (merged_audio.format or os.path.splitext(merged_audio.file_path)[1].lstrip('.') or 'mp3')
    filename = f"{_safe_filename(story.title if story else '', 'audiobook')}.{ext}"
    return FileResponse(
        path=merged_audio.file_path,
        filename=filename,
        media_type='application/octet-stream',
    )


def _reveal_in_file_manager(path: str) -> None:
    """Open the OS file manager with ``path`` selected (best effort)."""
    import subprocess
    import sys

    if sys.platform == "win32":
        # Explorer's /select is quoting-sensitive: the path must be quoted and
        # follow the comma with NO space (`/select,"C:\..."`), otherwise it
        # silently opens the wrong folder. A list-form argv adds that space, so
        # pass a single command-line string. Windows filenames can't contain a
        # double quote, so this is injection-safe. explorer returns exit code 1
        # even on success, so we don't check it.
        subprocess.Popen(f'explorer /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def _open_folder(path: str) -> None:
    """Open the OS file manager AT ``path`` (a directory), nothing selected."""
    import subprocess
    import sys

    if sys.platform == "win32":
        subprocess.Popen(f'explorer "{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


@router.post("/reveal-audio/{story_id}", dependencies=[Depends(require_localhost)])
async def reveal_merged_audio(story_id: str, db: Session = Depends(get_db)):
    """Open the file manager at the story's output folder.

    The desktop app already delivers everything to ``<output>/<story>/`` (the
    finished product plus the per-sentence ``segments/`` folder), so "download"
    is really "show me where it is" — and WebView2 can't trigger a programmatic
    blob download anyway. If a finished product exists we reveal it (selected);
    otherwise we just open the story folder so the user still sees the segments.
    """
    from app.services.segment_tts import story_output_name
    from app.services.output_delivery import get_output_folder

    merged_audio = db.query(models.MergedAudio).filter(
        models.MergedAudio.story_id == story_id
    ).order_by(models.MergedAudio.created_at.desc()).first()

    # Happy path: a finished product exists → reveal it with the file selected.
    if merged_audio and merged_audio.file_path and os.path.exists(merged_audio.file_path):
        path = os.path.normpath(merged_audio.file_path)
        try:
            _reveal_in_file_manager(path)
        except Exception as e:
            logger.error(f"[video] reveal audio failed: {e}")
            raise HTTPException(status_code=500, detail="Không mở được thư mục chứa file.")
        return {"revealed": path}

    # No product yet → fall back to opening the story folder (holds segments/).
    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    folder = get_output_folder(db) / story_output_name(story)
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Chưa có file audio nào cho truyện này.")
    try:
        _open_folder(os.path.normpath(str(folder)))
    except Exception as e:
        logger.error(f"[video] open story folder failed: {e}")
        raise HTTPException(status_code=500, detail="Không mở được thư mục truyện.")
    return {"opened": str(folder)}


@router.post("/validate-folder", response_model=schemas.VideoFolderValidateResponse)
async def validate_video_folder(request: schemas.VideoFolderValidateRequest):
    """Validate a folder containing background videos"""
    processor = VideoProcessor()
    result = processor.validate_video_folder(request.folder_path)
    return result


VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
STICKER_EXTENSIONS = {'.png', '.gif', '.webp', '.apng', '.jpg', '.jpeg'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}


@router.post("/browse", response_model=schemas.BrowseFolderResponse, dependencies=[Depends(require_localhost)])
async def browse_folder(request: schemas.BrowseFolderRequest):
    """Browse server filesystem to select a video folder"""
    path = request.path.strip()

    # If empty, return drive list on Windows or root on Unix
    if not path:
        if os.name == 'nt':
            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
            return {
                "current_path": "",
                "parent_path": None,
                "folders": drives,
                "video_count": 0
            }
        else:
            path = str(Path.home())

    folder = Path(path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Path not found: {path}")

    # List subdirectories
    folders = []
    video_count = 0
    try:
        for item in sorted(folder.iterdir()):
            try:
                if item.is_dir() and not item.name.startswith('.'):
                    folders.append(item.name)
                elif item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                    video_count += 1
            except PermissionError:
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")

    parent = str(folder.parent) if folder.parent != folder else None

    return {
        "current_path": str(folder),
        "parent_path": parent,
        "folders": folders,
        "video_count": video_count
    }


@router.post("/browse-files", response_model=schemas.BrowseFilesResponse, dependencies=[Depends(require_localhost)])
async def browse_files(request: schemas.BrowseFolderRequest):
    """Browse server filesystem to select an audio file"""
    path = request.path.strip()

    # If empty, return drive list on Windows or root on Unix
    if not path:
        if os.name == 'nt':
            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
            return {
                "current_path": "",
                "parent_path": None,
                "folders": drives,
                "files": []
            }
        else:
            path = str(Path.home())

    folder = Path(path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Path not found: {path}")

    folders = []
    files = []
    try:
        for item in sorted(folder.iterdir()):
            try:
                if item.is_dir() and not item.name.startswith('.'):
                    folders.append(item.name)
                elif item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS:
                    files.append(item.name)
            except PermissionError:
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")

    parent = str(folder.parent) if folder.parent != folder else None

    return {
        "current_path": str(folder),
        "parent_path": parent,
        "folders": folders,
        "files": files
    }


@router.post("/browse-images", response_model=schemas.BrowseFilesResponse, dependencies=[Depends(require_localhost)])
async def browse_images(request: schemas.BrowseFolderRequest):
    """Browse server filesystem to select an image file"""
    path = request.path.strip()

    # If empty, return drive list on Windows or root on Unix
    if not path:
        if os.name == 'nt':
            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
            return {
                "current_path": "",
                "parent_path": None,
                "folders": drives,
                "files": []
            }
        else:
            path = str(Path.home())

    folder = Path(path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Path not found: {path}")

    folders = []
    files = []
    try:
        for item in sorted(folder.iterdir()):
            try:
                if item.is_dir() and not item.name.startswith('.'):
                    folders.append(item.name)
                elif item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
                    files.append(item.name)
            except PermissionError:
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")

    parent = str(folder.parent) if folder.parent != folder else None

    return {
        "current_path": str(folder),
        "parent_path": parent,
        "folders": folders,
        "files": files
    }


@router.get("/preview-image", dependencies=[Depends(require_localhost)])
async def preview_image(path: str):
    """Serve an image file for preview"""
    file = Path(path)
    if not file.exists() or not file.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an image file")
    return FileResponse(str(file))


@router.get("/preview-video", dependencies=[Depends(require_localhost)])
async def preview_video(path: str):
    """Serve a video file for preview"""
    file = Path(path)
    if not file.exists() or not file.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file.suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not a video file")
    return FileResponse(str(file), media_type="video/mp4")


@router.get("/fonts")
async def get_fonts():
    """List available watermark text fonts."""
    return list_fonts()


@router.get("/fonts/{font_key}/file")
async def get_font_file(font_key: str):
    """Serve a font .ttf file for preview rendering. Auto-downloads if missing."""
    font_name, font_path = ensure_font(font_key)
    if not font_path:
        raise HTTPException(status_code=404, detail="Font is system-only, no file available")
    file = Path(font_path)
    if not file.exists():
        raise HTTPException(status_code=404, detail="Font file not found")
    return FileResponse(str(file), media_type="font/ttf", filename=file.name)


@router.get("/audio-duration", dependencies=[Depends(require_localhost)])
async def get_audio_duration(path: str):
    """Return duration in seconds of a media file at the given path."""
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    processor = VideoProcessor()
    dur = processor.get_media_duration(path)
    return {"duration": float(dur or 0.0)}


# --- Subtitle (SRT) upload + serve --------------------------------------------
# SRTs are stored under cache/srt/<story_id>/<uuid>.srt. They are scoped to one
# story (uploading for story A never returns paths usable from story B's UI)
# and swept after 1 hour of inactivity to keep the cache bounded.
_SRT_CACHE_DIR = paths.SRT_CACHE_DIR
_SRT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_SRT_TTL_SECONDS = 3600


def _sweep_srt_cache() -> None:
    """Drop SRT files (and their story dirs when empty) older than the TTL."""
    now = time.time()
    try:
        for story_dir in _SRT_CACHE_DIR.iterdir():
            if not story_dir.is_dir():
                continue
            for f in story_dir.glob("*.srt"):
                try:
                    if now - f.stat().st_mtime > _SRT_TTL_SECONDS:
                        f.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                # Remove the story dir if it's now empty.
                next(story_dir.iterdir())
            except StopIteration:
                story_dir.rmdir()
            except Exception:
                pass
    except Exception:
        pass


@router.post("/upload-srt")
async def upload_srt(
    story_id: str = Form(...),
    audio_path: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """Upload an SRT file scoped to a story. Returns its path + a warning if
    the SRT timing extends past the (sped-up) audio duration.

    Replaces any prior SRT for this story so the FE only references one file.
    """
    threading.Thread(target=_sweep_srt_cache, daemon=True).start()

    if not story_id or any(c in story_id for c in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="invalid story_id")

    fname = file.filename or "subtitle.srt"
    if not fname.lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail="Only .srt files are accepted")

    story_dir = _SRT_CACHE_DIR / story_id
    # Drop prior SRTs for this story — UI tracks one active SRT at a time.
    if story_dir.exists():
        for old in story_dir.glob("*.srt"):
            try:
                old.unlink()
            except Exception:
                pass
    story_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize destination filename to avoid path traversal via filename.
    safe_stem = "".join(
        c if c.isalnum() or c in ("-", "_") else "_"
        for c in Path(fname).stem
    )[:60] or "subtitle"
    dest = story_dir / f"{safe_stem}_{uuid.uuid4().hex[:8]}.srt"

    chunk_size = 256 * 1024
    written = 0
    max_bytes = 5 * 1024 * 1024  # 5 MB hard cap — SRTs are tiny
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

    # Probe SRT + audio duration, then surface a warning if SRT runs past audio.
    from app.services import subtitle_renderer
    try:
        meta = subtitle_renderer.probe_srt(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Cannot parse SRT: {e}")

    warning = None
    audio_duration = None
    if audio_path and os.path.exists(audio_path):
        try:
            audio_duration = float(VideoProcessor().get_media_duration(audio_path) or 0.0)
        except Exception:
            audio_duration = None
        if audio_duration and meta["last_end"] > audio_duration + 0.5:
            warning = (
                f"SRT runs to {meta['last_end']:.1f}s but audio is "
                f"{audio_duration:.1f}s — trailing lines will be truncated."
            )

    return {
        "srt_path": str(dest),
        "filename": fname,
        "segment_count": meta["segment_count"],
        "last_end": meta["last_end"],
        "first_start": meta["first_start"],
        "audio_duration": audio_duration,
        "warning": warning,
    }


@router.get("/srt-content")
async def srt_content(path: str):
    """Return raw SRT text for the FE preview overlay to parse client-side.

    Only serves files inside the SRT cache directory to prevent path traversal.
    """
    file = Path(path).resolve()
    try:
        file.relative_to(_SRT_CACHE_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path outside SRT cache")
    if not file.exists() or not file.is_file():
        raise HTTPException(status_code=404, detail="SRT not found")
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Read failed: {e}")
    return {"path": str(file), "content": text}


@router.get("/sample-clip", dependencies=[Depends(require_localhost)])
async def sample_clip(folder: str):
    """Return path to a random sample video clip from a folder"""
    import random
    folder_path = Path(folder)
    if not folder_path.exists() or not folder_path.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")
    clips = [
        str(f) for f in sorted(folder_path.iterdir())
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ]
    if not clips:
        raise HTTPException(status_code=404, detail="No video files in folder")
    return {"path": random.choice(clips)}


@router.get("/folder-clips", dependencies=[Depends(require_localhost)])
async def folder_clips(folder: str, limit: int = 200):
    """List clips in a folder (sorted by filename) with durations. Used by the
    frontend to build a playback schedule for the real-time preview."""
    folder_path = Path(folder)
    if not folder_path.exists() or not folder_path.is_dir():
        return {"clips": [], "total_duration": 0}
    processor = VideoProcessor()
    clips = processor.get_all_videos_in_folder(str(folder_path), order="name")
    if not clips:
        return {"clips": [], "total_duration": 0}
    clips = clips[:max(1, limit)]
    return {"clips": clips, "total_duration": sum(c["duration"] for c in clips)}


@router.get("/preview-audio", dependencies=[Depends(require_localhost)])
async def preview_audio(path: str):
    """Serve an audio file for the live preview <audio> element."""
    file = Path(path)
    if not file.exists() or not file.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file.suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an audio file")
    mime_map = {
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.flac': 'audio/flac',
        '.aac': 'audio/aac', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4',
        '.wma': 'audio/x-ms-wma',
    }
    media_type = mime_map.get(file.suffix.lower(), 'audio/mpeg')
    return FileResponse(str(file), media_type=media_type)


def _preview_config_hash(cfg: dict) -> str:
    # Hashes everything that affects the rendered output. story_id is excluded
    # because preview is story-agnostic — same config = same output.
    keys = [
        "video_source_folder", "audio_path", "audio_speed", "resolution",
        "banner_image", "banner_video_scale",
        "banner_video_offset_x", "banner_video_offset_y",
        "banner_video_scale_x", "banner_video_scale_y", "overlay_opacity",
        "watermark_image", "watermark_x", "watermark_y", "watermark_w", "watermark_h",
        "watermark_shape", "watermark_opacity",
        "watermark_text", "watermark_text_font", "watermark_text_size",
        "watermark_text_color", "watermark_text_angle",
        "watermark_text_x", "watermark_text_y", "watermark_text_opacity",
        "subtitle_srt_path", "subtitle_animation", "subtitle_font",
        "subtitle_font_size", "subtitle_color",
        "subtitle_outline_color", "subtitle_outline_width", "subtitle_shadow",
        "subtitle_bold", "subtitle_italic", "subtitle_align",
        "subtitle_x", "subtitle_y", "subtitle_opacity",
        "fade_in", "fade_out", "max_duration",
        "mute_source_videos",
        "transitions_pool", "transition_duration",
        "stickers",
        "_random_salt",
        *_AD_FIELDS,
        *_VIZ_FIELDS,
    ]
    payload = {k: cfg.get(k) for k in keys}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _sweep_preview_cache() -> None:
    # Drops cache files older than the TTL, plus stale _PREVIEW_JOBS entries
    # whose backing file is gone or whose terminal status is older than the
    # TTL. Keeps the in-memory dict from growing unboundedly across renders.
    now = time.time()
    try:
        for f in _PREVIEW_CACHE_DIR.glob("*.mp4"):
            try:
                if now - f.stat().st_mtime > _PREVIEW_TTL_SECONDS:
                    f.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass
    with _PREVIEW_LOCK:
        for h, job in list(_PREVIEW_JOBS.items()):
            if job.get("status") not in ("done", "failed"):
                continue
            if (now - job.get("started", now)) > _PREVIEW_TTL_SECONDS:
                _PREVIEW_JOBS.pop(h, None)


def _run_preview_render(job_hash: str, cfg: dict, output_path: str) -> None:
    def progress_cb(pct: int) -> None:
        with _PREVIEW_LOCK:
            job = _PREVIEW_JOBS.get(job_hash)
            if job is not None:
                job["progress"] = max(job.get("progress", 0), int(pct))

    with _PREVIEW_LOCK:
        _PREVIEW_JOBS[job_hash]["status"] = "running"
        _PREVIEW_JOBS[job_hash]["started"] = time.time()

    try:
        processor = VideoProcessor()
        result = processor.render_preview(
            video_source_folder=cfg["video_source_folder"],
            audio_path=cfg["audio_path"],
            output_path=output_path,
            max_duration=cfg.get("max_duration", 60.0),
            audio_speed=cfg.get("audio_speed", 1.07),
            resolution=cfg.get("resolution", "1920x1080"),
            banner_image=cfg.get("banner_image"),
            banner_video_scale=cfg.get("banner_video_scale", 1.0),
            banner_video_offset_x=cfg.get("banner_video_offset_x", 0.0),
            banner_video_offset_y=cfg.get("banner_video_offset_y", 0.0),
            banner_video_scale_x=cfg.get("banner_video_scale_x"),
            banner_video_scale_y=cfg.get("banner_video_scale_y"),
            overlay_opacity=cfg.get("overlay_opacity", 0.0),
            watermark_image=cfg.get("watermark_image"),
            watermark_x=cfg.get("watermark_x", 0.92),
            watermark_y=cfg.get("watermark_y", 0.92),
            watermark_w=cfg.get("watermark_w", 200),
            watermark_h=cfg.get("watermark_h", 200),
            watermark_shape=cfg.get("watermark_shape", "none"),
            watermark_opacity=cfg.get("watermark_opacity", 0.85),
            watermark_text=cfg.get("watermark_text"),
            watermark_text_font=cfg.get("watermark_text_font", "DejaVu Sans (system default)"),
            watermark_text_size=cfg.get("watermark_text_size", 48),
            watermark_text_color=cfg.get("watermark_text_color", "#FFFFFF"),
            watermark_text_angle=cfg.get("watermark_text_angle", 0.0),
            watermark_text_x=cfg.get("watermark_text_x", 0.92),
            watermark_text_y=cfg.get("watermark_text_y", 0.92),
            watermark_text_opacity=cfg.get("watermark_text_opacity", 0.85),
            subtitle_srt_path=cfg.get("subtitle_srt_path"),
            subtitle_animation=cfg.get("subtitle_animation", "fade"),
            subtitle_font=cfg.get("subtitle_font", "Be Vietnam Pro (Vietnamese)"),
            subtitle_font_size=cfg.get("subtitle_font_size", 56),
            subtitle_color=cfg.get("subtitle_color", "#FFFFFF"),
            subtitle_outline_color=cfg.get("subtitle_outline_color", "#000000"),
            subtitle_outline_width=cfg.get("subtitle_outline_width", 3),
            subtitle_shadow=cfg.get("subtitle_shadow", 0),
            subtitle_bold=cfg.get("subtitle_bold", True),
            subtitle_italic=cfg.get("subtitle_italic", False),
            subtitle_align=cfg.get("subtitle_align", "center"),
            subtitle_x=cfg.get("subtitle_x", 0.5),
            subtitle_y=cfg.get("subtitle_y", 0.85),
            subtitle_opacity=cfg.get("subtitle_opacity", 1.0),
            fade_in=cfg.get("fade_in", 0.0),
            fade_out=cfg.get("fade_out", 0.0),
            mute_source_videos=cfg.get("mute_source_videos", True),
            transitions_pool=cfg.get("transitions_pool"),
            transition_duration=cfg.get("transition_duration", 0.5),
            ad_flip_random=cfg.get("ad_flip_random", False),
            ad_flip_all=cfg.get("ad_flip_all", False),
            ad_zoom=cfg.get("ad_zoom", False),
            ad_zoom_factor=cfg.get("ad_zoom_factor", 1.08),
            ad_color=cfg.get("ad_color", False),
            ad_saturation=cfg.get("ad_saturation", 1.05),
            ad_contrast=cfg.get("ad_contrast", 1.00),
            ad_gamma=cfg.get("ad_gamma", 1.00),
            ad_hue_shift=cfg.get("ad_hue_shift", 0.0),
            ad_clip_speed_jitter=cfg.get("ad_clip_speed_jitter", False),
            ad_clip_speed_jitter_range=cfg.get("ad_clip_speed_jitter_range", 0.03),
            ad_strip_metadata=cfg.get("ad_strip_metadata", False),
            visualizer_enabled=cfg.get("visualizer_enabled", False),
            visualizer_style=cfg.get("visualizer_style", "bars"),
            visualizer_x=cfg.get("visualizer_x", 0.5),
            visualizer_y=cfg.get("visualizer_y", 0.85),
            visualizer_w=cfg.get("visualizer_w", 800),
            visualizer_h=cfg.get("visualizer_h", 120),
            visualizer_color1=cfg.get("visualizer_color1", "#00E5FF"),
            visualizer_color2=cfg.get("visualizer_color2", "#FF00FF"),
            visualizer_opacity=cfg.get("visualizer_opacity", 0.85),
            visualizer_bg_mode=cfg.get("visualizer_bg_mode", "transparent"),
            visualizer_bg_color=cfg.get("visualizer_bg_color", "#000000"),
            visualizer_bg_opacity=cfg.get("visualizer_bg_opacity", 0.3),
            visualizer_spectrum_preset=cfg.get("visualizer_spectrum_preset", "rainbow"),
            visualizer_bars_mode=cfg.get("visualizer_bars_mode", "bar"),
            visualizer_waveform_mode=cfg.get("visualizer_waveform_mode", "cline"),
            visualizer_waveform_mirror=cfg.get("visualizer_waveform_mirror", False),
            stickers=cfg.get("stickers") or [],
            progress_cb=progress_cb,
        )
        with _PREVIEW_LOCK:
            job = _PREVIEW_JOBS.get(job_hash)
            if job is None:
                return
            if result.get("success"):
                job["status"] = "done"
                job["progress"] = 100
                job["path"] = result["output_path"]
                job["duration"] = result.get("duration")
                job["file_size"] = result.get("file_size")
            else:
                job["status"] = "failed"
                job["error"] = result.get("error", "Unknown error")
    except Exception as e:
        logger.exception("Preview render crashed")
        with _PREVIEW_LOCK:
            job = _PREVIEW_JOBS.get(job_hash)
            if job is not None:
                job["status"] = "failed"
                job["error"] = str(e)


@router.post("/render-preview")
async def render_preview(request: schemas.VideoProcessRequest):
    """Async render a 60s exact preview using the same pipeline as the final video.

    Returns immediately with a job hash. Poll /preview-status?hash=... to track,
    then GET /preview-file?hash=... to download/play. If a recent (<1h) cached
    file already exists for the same config, it is reused.
    """
    threading.Thread(target=_sweep_preview_cache, daemon=True).start()

    audio_path = request.audio_path
    if not audio_path:
        raise HTTPException(status_code=400, detail="audio_path is required for preview")
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=400, detail=f"Audio file not found: {audio_path}")
    if not os.path.exists(request.video_source_folder):
        raise HTTPException(status_code=400, detail=f"Folder not found: {request.video_source_folder}")

    cfg = {
        "video_source_folder": request.video_source_folder,
        "audio_path": audio_path,
        "audio_speed": request.audio_speed,
        "resolution": request.resolution,
        "banner_image": request.banner_image,
        "banner_video_scale": request.banner_video_scale,
        "banner_video_offset_x": request.banner_video_offset_x,
        "banner_video_offset_y": request.banner_video_offset_y,
        "banner_video_scale_x": request.banner_video_scale_x,
        "banner_video_scale_y": request.banner_video_scale_y,
        "overlay_opacity": request.overlay_opacity,
        "watermark_image": request.watermark_image,
        "watermark_x": request.watermark_x,
        "watermark_y": request.watermark_y,
        "watermark_w": request.watermark_w,
        "watermark_h": request.watermark_h,
        "watermark_shape": request.watermark_shape,
        "watermark_opacity": request.watermark_opacity,
        "watermark_text": request.watermark_text,
        "watermark_text_font": request.watermark_text_font,
        "watermark_text_size": request.watermark_text_size,
        "watermark_text_color": request.watermark_text_color,
        "watermark_text_angle": request.watermark_text_angle,
        "watermark_text_x": request.watermark_text_x,
        "watermark_text_y": request.watermark_text_y,
        "watermark_text_opacity": request.watermark_text_opacity,
        "subtitle_srt_path": request.subtitle_srt_path,
        "subtitle_animation": request.subtitle_animation,
        "subtitle_font": request.subtitle_font,
        "subtitle_font_size": request.subtitle_font_size,
        "subtitle_color": request.subtitle_color,
        "subtitle_outline_color": request.subtitle_outline_color,
        "subtitle_outline_width": request.subtitle_outline_width,
        "subtitle_shadow": request.subtitle_shadow,
        "subtitle_bold": request.subtitle_bold,
        "subtitle_italic": request.subtitle_italic,
        "subtitle_align": request.subtitle_align,
        "subtitle_x": request.subtitle_x,
        "subtitle_y": request.subtitle_y,
        "subtitle_opacity": request.subtitle_opacity,
        "fade_in": request.fade_in,
        "fade_out": request.fade_out,
        "mute_source_videos": request.mute_source_videos,
        "transitions_pool": request.transitions_pool or [request.transition_effect],
        "transition_duration": request.transition_duration,
        "max_duration": 60.0,
        "stickers": [s.model_dump() for s in (request.stickers or [])],
        **_extract_ad_options(request),
        **_extract_viz_options(request),
    }
    # When randomness is on, mix a fresh salt into the hash so each request
    # bypasses cache and re-rolls (otherwise "Random flip" looks broken — same
    # config keeps returning the same cached output).
    if request.ad_flip_random or request.ad_clip_speed_jitter:
        cfg["_random_salt"] = uuid.uuid4().hex[:12]
    job_hash = _preview_config_hash(cfg)
    output_path = str(_PREVIEW_CACHE_DIR / f"{job_hash}.mp4")

    with _PREVIEW_LOCK:
        existing = _PREVIEW_JOBS.get(job_hash)

        if os.path.exists(output_path):
            age = time.time() - os.path.getmtime(output_path)
            if age <= _PREVIEW_TTL_SECONDS and (existing is None or existing.get("status") == "done"):
                _PREVIEW_JOBS[job_hash] = {
                    "status": "done", "progress": 100, "error": None,
                    "path": output_path, "started": time.time(),
                    "cached": True,
                }
                return {"hash": job_hash, "status": "done", "cached": True}

        if existing and existing.get("status") in ("queued", "running"):
            return {
                "hash": job_hash,
                "status": existing["status"],
                "progress": existing.get("progress", 0),
                "cached": False,
            }

        _PREVIEW_JOBS[job_hash] = {
            "status": "queued", "progress": 0, "error": None,
            "path": None, "started": time.time(), "cached": False,
        }

    threading.Thread(
        target=_run_preview_render,
        args=(job_hash, cfg, output_path),
        daemon=True,
    ).start()
    return {"hash": job_hash, "status": "queued", "cached": False}


@router.get("/preview-status")
async def preview_status(hash: str):
    """Poll status of a render-preview job."""
    with _PREVIEW_LOCK:
        job = _PREVIEW_JOBS.get(hash)
        if job is None:
            # Server may have restarted while a cached file is still on disk.
            f = _PREVIEW_CACHE_DIR / f"{hash}.mp4"
            if f.exists() and (time.time() - f.stat().st_mtime) <= _PREVIEW_TTL_SECONDS:
                return {"status": "done", "progress": 100, "cached": True}
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "status": job["status"],
            "progress": job.get("progress", 0),
            "error": job.get("error"),
            "cached": job.get("cached", False),
            "duration": job.get("duration"),
            "file_size": job.get("file_size"),
        }


@router.get("/preview-file")
async def preview_file(hash: str):
    """Serve a rendered preview mp4 by job hash."""
    f = _PREVIEW_CACHE_DIR / f"{hash}.mp4"
    if not f.exists():
        raise HTTPException(status_code=404, detail="Preview file not found")
    return FileResponse(str(f), media_type="video/mp4")


# --- Sticker library + upload + serve -----------------------------------------
# Built-in library lives in <backend>/stickers/<category>/<file>. User uploads
# go to <backend>/cache/stickers_upload/<uuid>.<ext> and their absolute path is
# stored directly in VideoConfig.stickers (no story scoping — stickers are
# reusable across stories).
_STICKER_LIB_DIR = paths.STICKERS_DIR
_STICKER_UPLOAD_DIR = paths.STICKER_UPLOAD_DIR
_STICKER_LIB_DIR.mkdir(parents=True, exist_ok=True)
_STICKER_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_STICKER_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap per file
_STICKER_ANIMATED_EXTS = {".gif", ".webp", ".apng"}


def _sticker_safe_path(p: str) -> Path:
    """Resolve a path and confirm it lives under the library or upload dirs.

    Used by the file-serving endpoint to block path traversal.
    """
    abs_p = Path(p).resolve()
    lib = _STICKER_LIB_DIR.resolve()
    up = _STICKER_UPLOAD_DIR.resolve()
    try:
        abs_p.relative_to(lib)
        return abs_p
    except ValueError:
        pass
    try:
        abs_p.relative_to(up)
        return abs_p
    except ValueError:
        pass
    raise HTTPException(status_code=403, detail="Path outside sticker dirs")


@router.get("/stickers/library")
async def stickers_library():
    """List built-in stickers grouped by category (one subfolder per category).

    Returns absolute paths the FE can echo back into VideoConfig.stickers.
    Animated flag is inferred from extension so the UI can mark GIFs.
    """
    categories = []
    if not _STICKER_LIB_DIR.exists():
        return {"categories": []}

    for cat_dir in sorted(_STICKER_LIB_DIR.iterdir()):
        if not cat_dir.is_dir() or cat_dir.name.startswith("."):
            continue
        items = []
        for f in sorted(cat_dir.iterdir()):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext not in STICKER_EXTENSIONS:
                continue
            items.append({
                "id": f"{cat_dir.name}/{f.stem}",
                "name": f.stem.replace("-", " ").replace("_", " ").title(),
                "path": str(f.resolve()),
                "animated": ext in _STICKER_ANIMATED_EXTS,
                "ext": ext.lstrip("."),
            })
        if items:
            categories.append({
                "name": cat_dir.name,
                "label": cat_dir.name.replace("-", " ").replace("_", " ").title(),
                "stickers": items,
            })
    return {"categories": categories}


@router.post("/stickers/upload")
async def stickers_upload(file: UploadFile = File(...)):
    """Upload a custom sticker (PNG/GIF/WebP/APNG/JPG). Stored in the upload
    cache; returns the absolute path the FE puts into VideoConfig.stickers."""
    fname = file.filename or "sticker.png"
    ext = Path(fname).suffix.lower()
    if ext not in STICKER_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sticker type. Allowed: {sorted(STICKER_EXTENSIONS)}",
        )

    safe_stem = "".join(
        c if c.isalnum() or c in ("-", "_") else "_"
        for c in Path(fname).stem
    )[:60] or "sticker"
    dest = _STICKER_UPLOAD_DIR / f"{safe_stem}_{uuid.uuid4().hex[:8]}{ext}"

    chunk_size = 256 * 1024
    written = 0
    with open(dest, "wb") as f_out:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > _STICKER_MAX_BYTES:
                f_out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Sticker file too large (max 5MB)")
            f_out.write(chunk)

    return {
        "path": str(dest.resolve()),
        "filename": fname,
        "animated": ext in _STICKER_ANIMATED_EXTS,
        "ext": ext.lstrip("."),
        "size": written,
    }


@router.get("/stickers/file")
async def stickers_file(path: str):
    """Serve a sticker file by absolute path (must reside under library or
    upload dir). Used both by the picker grid and the FE preview overlay."""
    file = _sticker_safe_path(path)
    if not file.exists() or not file.is_file():
        raise HTTPException(status_code=404, detail="Sticker not found")
    ext = file.suffix.lower()
    media_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".apng": "image/apng",
    }
    return FileResponse(str(file), media_type=media_map.get(ext, "application/octet-stream"))
