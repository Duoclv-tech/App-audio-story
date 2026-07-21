"""
OmniVoice local TTS engine (embedded).

This is the second TTS engine alongside VbeeTTSProcessor. It loads the
OmniVoice / KhanhTTS model into the backend process (on GPU) and generates
audio locally — supporting voice *clone* (from a reference sample) and voice
*design* (natural-language voice description), which the VBEE cloud API cannot.

Heavy deps (torch / omnivoice / soundfile) are imported lazily so the backend
boots fine on machines without a GPU or without these packages installed — in
that case ``OmniVoiceProcessor.availability()`` reports why and VBEE keeps
working. Output WAV @ 24 kHz is transcoded to mp3 via ffmpeg so the rest of the
pipeline (merge / video) is unchanged.
"""
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app import models, paths
from app.config import settings
from app.services.output_delivery import deliver_final, safe_file_stem

SR = 24000  # OmniVoice native sample rate

# Only the OmniVoice base (omnilingual) model is used. The KhanhTTS fine-tune
# was dropped, so "base" is the sole option and the default.
MODEL_PATHS = {
    "base": settings.OMNIVOICE_BASE_PATH,
}
DEFAULT_MODEL_KEY = "base"

# --- Lazy model singleton --------------------------------------------------
# One model is held in VRAM for the process lifetime. A lock serialises
# generate() calls (single GPU) and guards model swaps.
_model_lock = threading.Lock()
_loaded: Dict[str, object] = {"key": None, "model": None}


def _import_stack():
    """Import the heavy deps, raising a clear error if unavailable."""
    import truststore  # noqa: F401  (SSL for HF downloads elsewhere)
    import torch
    import soundfile as sf
    from omnivoice import OmniVoice
    return torch, sf, OmniVoice


def _model_available(key: str) -> bool:
    path = MODEL_PATHS.get(key)
    # Gate on the actual weights file, not config.json — config.json downloads
    # first (tiny), so checking it would report "ready" while GBs are still
    # downloading, hiding the progress UI prematurely.
    return bool(path) and (Path(path) / "model.safetensors").exists()


def availability() -> Dict:
    """Report whether the OmniVoice engine can run, and why not if it can't.

    Returns a dict the UI uses to enable/disable the OmniVoice tab and to show
    a "download model" prompt.
    """
    info = {
        "enabled": settings.OMNIVOICE_ENABLED,
        "deps_installed": False,
        "gpu_available": False,
        "device": settings.OMNIVOICE_DEVICE,
        "models": {
            key: _model_available(key) for key in MODEL_PATHS
        },
        "loaded_model": _loaded["key"],
        "reason": "",
    }
    if not settings.OMNIVOICE_ENABLED:
        info["reason"] = "OmniVoice disabled in settings"
        return info
    try:
        import torch  # noqa
        info["deps_installed"] = True
    except Exception as e:
        info["reason"] = f"missing python deps (torch/omnivoice): {e}"
        return info
    try:
        import torch
        info["gpu_available"] = bool(torch.cuda.is_available())
    except Exception:
        info["gpu_available"] = False
    if settings.OMNIVOICE_DEVICE.startswith("cuda") and not info["gpu_available"]:
        info["reason"] = "no CUDA GPU detected"
    elif not any(info["models"].values()):
        info["reason"] = "model not downloaded yet"
    else:
        info["ready"] = True
    return info


def is_ready() -> bool:
    a = availability()
    return bool(a.get("ready"))


def _get_model_sync(key: str):
    """Lazy-load the model on first use; swap (freeing VRAM) if key changes."""
    if key not in MODEL_PATHS:
        raise ValueError(f"unknown OmniVoice model: {key}")
    if not _model_available(key):
        raise RuntimeError(
            f"OmniVoice model '{key}' not found at {MODEL_PATHS[key]} "
            f"(download it first)"
        )
    if _loaded["key"] == key and _loaded["model"] is not None:
        return _loaded["model"]

    torch, _sf, OmniVoice = _import_stack()

    if _loaded["model"] is not None:
        logger.info(f"[omnivoice] Unloading previous model: {_loaded['key']}")
        del _loaded["model"]
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        _loaded["model"] = None
        _loaded["key"] = None

    device = settings.OMNIVOICE_DEVICE
    dtype = torch.float16 if device.startswith("cuda") else torch.float32
    logger.info(f"[omnivoice] Loading model '{key}' from {MODEL_PATHS[key]} on {device}")
    t0 = time.time()
    model = OmniVoice.from_pretrained(MODEL_PATHS[key], device_map=device, dtype=dtype)
    logger.info(f"[omnivoice] Loaded '{key}' in {time.time() - t0:.1f}s")
    _loaded["key"] = key
    _loaded["model"] = model
    return model


def unload_model() -> None:
    """Free VRAM (e.g. before switching to a VRAM-heavy video job)."""
    with _model_lock:
        if _loaded["model"] is None:
            return
        try:
            import torch
            del _loaded["model"]
            torch.cuda.empty_cache()
        except Exception:
            pass
        _loaded["model"] = None
        _loaded["key"] = None


def _normalize_language(lang: Optional[str]) -> Optional[str]:
    if not lang or str(lang).lower() == "auto":
        return None
    return lang


def _wav_to_mp3(wav_path: Path, mp3_path: Path, bitrate: int = 128,
                speed: float = 1.0) -> None:
    """Transcode WAV -> mp3 via ffmpeg, applying speed with pitch preserved.

    ffmpeg atempo only accepts 0.5..2.0 per filter, so speeds outside that get
    chained. speed=1.0 => no tempo filter.
    """
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(wav_path)]
    if abs(speed - 1.0) > 1e-3:
        factors: List[float] = []
        remaining = max(0.1, min(speed, 100.0))
        while remaining > 2.0:
            factors.append(2.0)
            remaining /= 2.0
        while remaining < 0.5:
            factors.append(0.5)
            remaining /= 0.5
        factors.append(remaining)
        cmd += ["-filter:a", ",".join(f"atempo={f:.4f}" for f in factors)]
    cmd += ["-b:a", f"{bitrate}k", str(mp3_path)]
    subprocess.run(cmd, check=True, capture_output=True)


class OmniVoiceProcessor:
    """Local TTS engine mirroring VbeeTTSProcessor's chapter/story/merged API."""

    def __init__(self, db: Optional[Session] = None):
        self.db = db

    # -- core generation ----------------------------------------------------
    def _build_kwargs(self, text, config: Dict) -> Dict:
        mode = (config.get("mode") or "auto").lower()
        lang = _normalize_language(config.get("language"))
        kwargs: Dict = {"text": text, "language": lang}

        if mode == "auto":
            pass
        elif mode == "design":
            instruct = (config.get("instruct") or "").strip()
            if not instruct:
                raise ValueError("instruct is required for design mode")
            kwargs["instruct"] = instruct
        elif mode == "clone":
            from app.services import clone_preset_store as presets
            preset_id = (config.get("preset_id") or "").strip()
            if not preset_id:
                raise ValueError("preset_id is required for clone mode")
            audio_path, ref_text = presets.resolve_audio_and_text(preset_id)
            kwargs["ref_audio"] = audio_path
            kwargs["ref_text"] = ref_text
        else:
            raise ValueError(f"unknown OmniVoice mode: {mode}")
        return kwargs

    def generate_wav(self, text, config: Dict):
        """Generate audio; returns a list of numpy arrays (one per input text)."""
        model_key = config.get("model_key") or config.get("voice_code") or DEFAULT_MODEL_KEY
        if model_key not in MODEL_PATHS:
            model_key = DEFAULT_MODEL_KEY
        kwargs = self._build_kwargs(text, config)
        with _model_lock:
            model = _get_model_sync(model_key)
            t0 = time.time()
            audios = model.generate(**kwargs)
            logger.info(f"[omnivoice] generated in {time.time() - t0:.2f}s "
                        f"(model={model_key}, mode={config.get('mode')})")
        return audios

    def _generate_to_mp3(self, text: str, config: Dict, out_path: Path) -> float:
        """Generate one text -> mp3 file. Returns audio duration in seconds."""
        _torch, sf, _OV = _import_stack()
        audios = self.generate_wav(text, config)
        audio = audios[0]
        if audio is None or getattr(audio, "size", 0) == 0:
            raise RuntimeError("model returned empty audio")
        tmp_wav = paths.TRIM_TEMP_DIR / f"omnivoice_{int(time.time()*1000)}.wav"
        tmp_wav.parent.mkdir(parents=True, exist_ok=True)
        try:
            sf.write(str(tmp_wav), audio, SR, subtype="PCM_16")
            _wav_to_mp3(
                tmp_wav, out_path,
                bitrate=int(config.get("bitrate", 128)),
                speed=float(config.get("speed", 1.0)),
            )
        finally:
            tmp_wav.unlink(missing_ok=True)
        return len(audio) / SR

    # -- pipeline-compatible entry points -----------------------------------
    async def process_merged_content(
        self, story_id: str, db: Session, config: Optional[Dict] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict:
        """Generate a single mp3 from story.merged_content and save MergedAudio."""
        import asyncio
        config = config or {}
        try:
            story = db.query(models.Story).filter(models.Story.id == story_id).first()
            if not story:
                return {"success": False, "error": "Story not found"}
            if not story.merged_content or not story.merged_content.strip():
                return {"success": False,
                        "error": "No merged content found. Please edit content in Grammar step first."}

            merged_content = story.merged_content.strip()
            logger.info(f"[omnivoice] merged story {story_id}, {len(merged_content)} chars")
            if progress_callback:
                progress_callback(f"OmniVoice generating {len(merged_content)} chars...")

            story_folder = (story.title or f"story_{story_id}").replace(' ', '_').replace('/', '_')
            output_dir = Path(settings.STORAGE_PATH) / "audio" / story_folder
            output_path = output_dir / "merged_audio.mp3"

            duration = await asyncio.to_thread(
                self._generate_to_mp3, merged_content, config, output_path
            )
            file_size = os.path.getsize(output_path)

            # Deliver finished audio to the user's output folder (Downloads default)
            _name = safe_file_stem(story.title if story and story.title else story_id, story_id)
            final_path = deliver_final(str(output_path), db, filename=f"{_name}.mp3")

            merged_audio = db.query(models.MergedAudio).filter(
                models.MergedAudio.story_id == story_id
            ).first()
            if merged_audio:
                merged_audio.file_path = final_path
                merged_audio.file_size = file_size
                merged_audio.duration = duration
                merged_audio.format = "mp3"
            else:
                merged_audio = models.MergedAudio(
                    story_id=story_id, file_path=final_path,
                    file_size=file_size, duration=duration, format="mp3",
                )
                db.add(merged_audio)
            db.commit()

            logger.info(f"[omnivoice] merged done: {final_path} ({duration:.1f}s)")
            return {
                "success": True, "story_id": story_id, "file_path": final_path,
                "file_size": file_size, "duration": duration,
                "char_count": len(merged_content),
            }
        except Exception as e:
            logger.error(f"[omnivoice] merged failed for {story_id}: {e}")
            return {"success": False, "error": str(e)}

    async def process_chapter(
        self, chapter_id: str, db: Session, config: Optional[Dict] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict:
        import asyncio
        config = config or {}
        audio_record = None
        try:
            chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
            if not chapter:
                return {"success": False, "error": "Chapter not found"}

            audio_record = db.query(models.AudioFile).filter(
                models.AudioFile.chapter_id == chapter_id
            ).first()

            if not chapter.content or not chapter.content.strip():
                if audio_record:
                    audio_record.status = "skipped"
                    audio_record.error_message = "Empty content - skipped"
                    db.commit()
                return {"success": True, "skipped": True,
                        "chapter_number": chapter.chapter_number, "reason": "Empty content"}

            if not audio_record:
                audio_record = models.AudioFile(
                    chapter_id=chapter_id, format="mp3",
                    bitrate=str(config.get("bitrate", 128)), status="processing")
                db.add(audio_record)
                db.commit()
                db.refresh(audio_record)
            else:
                audio_record.status = "processing"
                db.commit()

            story = db.query(models.Story).filter(models.Story.id == chapter.story_id).first()
            story_folder = (story.title.replace(' ', '_') if story else "unknown_story")
            output_dir = Path(settings.STORAGE_PATH) / "audio" / story_folder
            output_path = output_dir / f"chapter_{chapter.chapter_number}.mp3"

            duration = await asyncio.to_thread(
                self._generate_to_mp3, chapter.content, config, output_path
            )

            audio_record.file_path = str(output_path)
            audio_record.file_size = os.path.getsize(output_path)
            audio_record.duration = duration
            audio_record.status = "success"
            audio_record.error_message = None
            db.commit()
            return {"success": True, "chapter_number": chapter.chapter_number,
                    "audio_file": str(output_path)}
        except Exception as e:
            logger.error(f"[omnivoice] chapter {chapter_id} failed: {e}")
            if audio_record:
                audio_record.status = "failed"
                audio_record.error_message = str(e)
                db.commit()
            else:
                db.rollback()
            return {"success": False, "error": str(e)}

    async def process_story(
        self, story_id: str, task_id: str, db: Session,
        config: Optional[Dict] = None, **_ignore,
    ) -> Dict:
        config = config or {}
        try:
            chapters = db.query(models.Chapter).filter(
                models.Chapter.story_id == story_id
            ).order_by(models.Chapter.chapter_number).all()
            if not chapters:
                return {"success": False, "error": "No chapters found"}

            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                task.total_items = len(chapters)
                task.status = "running"
                db.commit()

            results = []
            for chapter in chapters:  # serial: single GPU, no concurrency win
                result = await self.process_chapter(chapter.id, db, config)
                results.append(result)
                if task:
                    task.completed_items = (task.completed_items or 0) + 1
                    task.progress = int((task.completed_items / task.total_items) * 100)
                    db.commit()

            successful = sum(1 for r in results if r.get("success"))
            failed = len(results) - successful
            if task:
                task.status = "completed" if failed == 0 else "completed_with_errors"
                if failed:
                    task.error_message = f"{failed} chapters failed"
                else:
                    task.progress = 100
                db.commit()
            return {"success": True, "total_chapters": len(chapters),
                    "successful": successful, "failed": failed, "results": results}
        except Exception as e:
            logger.error(f"[omnivoice] story {story_id} failed: {e}")
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                task.status = "failed"
                task.error_message = str(e)
                db.commit()
            return {"success": False, "error": str(e)}
