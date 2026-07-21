"""
TTS Processor Service
Integration with VBEE TTS Official API for text-to-speech conversion
API Docs: https://vbee.vn/api/v1/tts
"""
import os
import time
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Callable
from datetime import datetime

import requests
from sqlalchemy import update
from sqlalchemy.orm import Session
from loguru import logger

from app import models
from app.config import settings
from app.database import SessionLocal
from app.services.output_delivery import deliver_final, safe_file_stem


class VbeeTTSProcessor:
    """Service for processing text-to-speech using VBEE Official API"""

    def __init__(self, app_id: Optional[str] = None, bearer_token: Optional[str] = None, db: Optional[Session] = None):
        """
        Initialize VBEE TTS processor

        Args:
            app_id: VBEE App ID (or from settings/db)
            bearer_token: JWT Bearer token (or from settings/db)
            db: Database session to load settings from database
        """
        self.base_url = "https://vbee.vn/api/v1"

        # Try to load from database first, then fall back to .env
        if db:
            db_app_id = self._get_setting_from_db(db, 'VBEE_APP_ID')
            db_bearer = self._get_setting_from_db(db, 'VBEE_BEARER_TOKEN')
            self.app_id = app_id or db_app_id or settings.VBEE_APP_ID
            self.bearer_token = bearer_token or db_bearer or settings.VBEE_BEARER_TOKEN

            if db_app_id:
                logger.info("Using VBEE_APP_ID from database")
            if db_bearer:
                logger.info("Using VBEE_BEARER_TOKEN from database")
        else:
            self.app_id = app_id or settings.VBEE_APP_ID
            self.bearer_token = bearer_token or settings.VBEE_BEARER_TOKEN

        self.session = requests.Session()

        # Headers with Bearer token authentication
        self.headers = {
            'Content-Type': 'application/json',
        }
        if self.bearer_token:
            self.headers['Authorization'] = f'Bearer {self.bearer_token}'
        else:
            logger.warning("No VBEE_BEARER_TOKEN configured!")

    def _get_setting_from_db(self, db: Session, key: str) -> Optional[str]:
        """Get setting value from database"""
        try:
            setting = db.query(models.Setting).filter(models.Setting.setting_key == key).first()
            if setting and setting.setting_value:
                value = setting.setting_value
                # Remove JSON quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                return value
            return None
        except Exception as e:
            logger.warning(f"Error loading setting {key} from database: {e}")
            return None

    def update_credentials(self, app_id: str = None, bearer_token: str = None):
        """
        Update VBEE credentials

        Args:
            app_id: New App ID
            bearer_token: New Bearer Token
        """
        if app_id:
            self.app_id = app_id
            logger.info(f"Updated VBEE App ID: {app_id[:8]}...")
        if bearer_token:
            self.bearer_token = bearer_token
            self.headers['Authorization'] = f'Bearer {bearer_token}'
            logger.info("Updated VBEE Bearer Token")

    async def text_to_speech(
        self,
        text: str,
        voice_code: str = "hn_female_ngochuyen_full_48k-fhg",
        audio_type: str = "mp3",
        bitrate: int = 128,
        speed: float = 1.0,
        callback_url: str = None
    ) -> Optional[Dict]:
        """
        Convert text to speech using VBEE Official API

        API: POST https://vbee.vn/api/v1/tts

        Args:
            text: Text to convert (input_text)
            voice_code: Voice identifier
            audio_type: Output format (mp3, wav)
            bitrate: Audio quality (8, 16, 32, 64, 128)
            speed: Speaking speed (0.1 - 1.9)
            callback_url: Webhook URL for async result (optional)

        Returns:
            API response dict or None if error
        """
        url = f"{self.base_url}/tts"

        # callback_url is REQUIRED by VBEE API
        # Use provided callback_url or a dummy one (we'll poll for results anyway)
        actual_callback = callback_url or "https://webhook.site/dummy-callback"

        payload = {
            "app_id": self.app_id,
            "response_type": "indirect",
            "callback_url": actual_callback,
            "input_text": text,
            "voice_code": voice_code,
            "audio_type": audio_type,
            "bitrate": bitrate,
            "speed_rate": str(speed),
        }

        try:
            logger.debug(f"TTS Request: voice={voice_code}, chars={len(text)}")
            response = self.session.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            result = response.json()

            if result.get('status') == 1:
                logger.info(f"TTS request created: request_id={result['result'].get('request_id')}")
                return result['result']
            else:
                logger.error(f"VBEE API error: {result.get('error_message', 'Unknown error')}")
                return None

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error {e.response.status_code}: {e}")
            try:
                error_detail = e.response.json()
                logger.error(f"Error details: {json.dumps(error_detail, indent=2, ensure_ascii=False)}")
            except:
                logger.error(f"Error details: {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None

    async def get_request_status(self, request_id: str) -> Optional[Dict]:
        """
        Get TTS request status

        API: GET https://vbee.vn/api/v1/tts/{request_id}

        Args:
            request_id: VBEE request ID

        Returns:
            Request status dict or None if error
        """
        url = f"{self.base_url}/tts/{request_id}"

        try:
            response = self.session.get(url, headers=self.headers)
            response.raise_for_status()
            result = response.json()

            if result.get('status') == 1:
                return result['result']
            else:
                logger.error(f"Error getting request status: {result.get('error_message')}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting request status: {e}")
            return None

    async def get_audio_link(self, request_id: str, max_retries: int = 60, retry_interval: int = 5) -> Optional[str]:
        """
        Poll for audio link until ready

        Args:
            request_id: VBEE request ID
            max_retries: Maximum number of retries (default 60 = 5 minutes with 5s interval)
            retry_interval: Seconds between retries

        Returns:
            Audio URL or None if not found
        """
        for attempt in range(1, max_retries + 1):
            try:
                result = await self.get_request_status(request_id)

                if result:
                    status = result.get('status')

                    if status == 'SUCCESS':
                        audio_link = result.get('audio_link')
                        if audio_link:
                            logger.info(f"Audio ready: {request_id}")
                            return audio_link

                    elif status == 'FAILURE':
                        logger.error(f"TTS failed for request {request_id}")
                        return None

                    elif status == 'IN_PROGRESS':
                        progress = result.get('progress', 0)
                        logger.debug(f"Request {request_id}: {progress}% (attempt {attempt}/{max_retries})")

                # Wait before next retry
                if attempt < max_retries:
                    await asyncio.sleep(retry_interval)

            except Exception as e:
                logger.error(f"Error polling audio link: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(retry_interval)

        logger.warning(f"Could not get audio link after {max_retries} attempts")
        return None

    async def download_audio(self, audio_url: str, output_path: str) -> bool:
        """
        Download audio file from URL

        Args:
            audio_url: URL of audio file
            output_path: Path to save file

        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(audio_url, stream=True)
            response.raise_for_status()

            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Download file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Downloaded audio to: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Error downloading audio: {e}")
            return False

    async def process_chapter(
        self,
        chapter_id: str,
        db: Session,
        voice_code: str = "hn_female_ngochuyen_full_48k-fhg",
        audio_type: str = "mp3",
        bitrate: int = 128,
        speed: float = 1.0,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """
        Process a single chapter to audio

        Args:
            chapter_id: Chapter ID to process
            db: Database session
            voice_code: Voice to use
            audio_type: Output format
            bitrate: Audio quality
            speed: Speaking speed
            progress_callback: Optional callback for progress

        Returns:
            Dictionary with processing results
        """
        audio_record = None
        try:
            # Get chapter from database
            chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
            if not chapter:
                return {"success": False, "error": "Chapter not found"}

            # Skip chapters with empty content
            if not chapter.content or chapter.content.strip() == "":
                logger.info(f"Skipping chapter {chapter.chapter_number} - empty content")
                # Update audio record status to skipped if exists
                audio_record = db.query(models.AudioFile).filter(
                    models.AudioFile.chapter_id == chapter_id
                ).first()
                if audio_record:
                    audio_record.status = "skipped"
                    audio_record.error_message = "Empty content - skipped"
                    db.commit()
                return {
                    "success": True,
                    "skipped": True,
                    "chapter_number": chapter.chapter_number,
                    "reason": "Empty content"
                }

            # Get audio record (should exist from /prepare call)
            audio_record = db.query(models.AudioFile).filter(
                models.AudioFile.chapter_id == chapter_id
            ).first()

            if not audio_record:
                # Create if not exists (fallback)
                audio_record = models.AudioFile(
                    chapter_id=chapter_id,
                    format=audio_type,
                    bitrate=str(bitrate),
                    status="processing"
                )
                db.add(audio_record)
                db.commit()
                db.refresh(audio_record)
            else:
                # Update status to processing
                audio_record.status = "processing"
                db.commit()

            if progress_callback:
                progress_callback(f"Processing chapter {chapter.chapter_number}...")

            # Call TTS API
            tts_result = await self.text_to_speech(
                text=chapter.content,
                voice_code=voice_code,
                audio_type=audio_type,
                bitrate=bitrate,
                speed=speed
            )

            if not tts_result:
                audio_record.status = "failed"
                audio_record.error_message = "TTS API failed"
                db.commit()
                return {"success": False, "error": "TTS API failed"}

            request_id = tts_result.get('request_id')
            if not request_id:
                audio_record.status = "failed"
                audio_record.error_message = "No request ID received"
                db.commit()
                return {"success": False, "error": "No request ID received"}

            # Save request_id
            audio_record.request_id = request_id
            db.commit()

            # Wait for audio to be ready
            if progress_callback:
                progress_callback(f"Waiting for audio generation...")

            audio_link = await self.get_audio_link(request_id)
            if not audio_link:
                audio_record.status = "failed"
                audio_record.error_message = "Could not get audio link"
                db.commit()
                return {"success": False, "error": "Could not get audio link"}

            # Save audio_link
            audio_record.audio_link = audio_link
            db.commit()

            # Define output path
            story = db.query(models.Story).filter(models.Story.id == chapter.story_id).first()
            story_folder = story.title.replace(' ', '_') if story else "unknown_story"
            output_dir = Path(settings.STORAGE_PATH) / "audio" / story_folder
            output_path = output_dir / f"chapter_{chapter.chapter_number}.{audio_type}"

            # Download audio
            if progress_callback:
                progress_callback(f"Downloading audio...")

            success = await self.download_audio(audio_link, str(output_path))
            if not success:
                audio_record.status = "failed"
                audio_record.error_message = "Failed to download audio"
                db.commit()
                return {"success": False, "error": "Failed to download audio"}

            # Update audio record with success status
            audio_record.file_path = str(output_path)
            audio_record.file_size = os.path.getsize(output_path)
            audio_record.status = "success"
            audio_record.error_message = None
            db.commit()

            return {
                "success": True,
                "chapter_number": chapter.chapter_number,
                "audio_file": str(output_path),
                "request_id": request_id,
                "audio_link": audio_link
            }

        except Exception as e:
            logger.error(f"Error processing chapter {chapter_id}: {e}")
            if audio_record:
                audio_record.status = "failed"
                audio_record.error_message = str(e)
                db.commit()
            else:
                db.rollback()
            return {"success": False, "error": str(e)}

    async def process_story(
        self,
        story_id: str,
        task_id: str,
        db: Session,
        voice_code: str = "hn_female_ngochuyen_full_48k-fhg",
        audio_type: str = "mp3",
        bitrate: int = 128,
        speed: float = 1.0,
        max_concurrent: int = 2
    ) -> Dict:
        """
        Process all chapters of a story to audio

        Args:
            story_id: Story ID to process
            task_id: Task ID for progress tracking
            db: Database session
            voice_code: Voice to use
            audio_type: Output format
            bitrate: Audio quality
            speed: Speaking speed
            max_concurrent: Maximum concurrent TTS requests

        Returns:
            Dictionary with overall results
        """
        try:
            # Get all chapters
            chapters = db.query(models.Chapter).filter(
                models.Chapter.story_id == story_id
            ).order_by(models.Chapter.chapter_number).all()

            if not chapters:
                return {"success": False, "error": "No chapters found"}

            # Update task
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                task.total_items = len(chapters)
                task.status = "running"
                db.commit()

            results = []
            semaphore = asyncio.Semaphore(max_concurrent)
            total_items = len(chapters)

            async def process_with_limit(chapter):
                async with semaphore:
                    # Each concurrent chapter gets its OWN session — a SQLAlchemy
                    # Session is not safe to share across coroutines that commit
                    # (one coroutine's commit would flush another's half-done
                    # changes and corrupt the identity map / task counters).
                    cdb = SessionLocal()
                    try:
                        result = await self.process_chapter(
                            chapter_id=chapter.id,
                            db=cdb,
                            voice_code=voice_code,
                            audio_type=audio_type,
                            bitrate=bitrate,
                            speed=speed
                        )

                        # Bump progress with an ATOMIC UPDATE (not read-modify-write)
                        # so two concurrent chapters can't both read the same
                        # completed_items and clobber each other's increment.
                        cdb.execute(
                            update(models.Task)
                            .where(models.Task.id == task_id)
                            .values(
                                completed_items=models.Task.completed_items + 1,
                                progress=(models.Task.completed_items + 1) * 100 // total_items,
                            )
                        )
                        cdb.commit()
                    finally:
                        cdb.close()

                    # Add delay between requests to avoid rate limiting
                    await asyncio.sleep(2)
                    return result

            # Process all chapters
            tasks = [process_with_limit(chapter) for chapter in chapters]
            results = await asyncio.gather(*tasks)

            # Update task status
            successful = sum(1 for r in results if r.get("success"))
            failed = len(results) - successful

            if task:
                # The per-coroutine sessions incremented completed_items behind
                # this session's back, so `task` is stale — refresh before the
                # final write, otherwise committing it would overwrite
                # completed_items back to the value loaded at "running".
                db.refresh(task)
                if failed == 0:
                    task.status = "completed"
                    task.progress = 100
                else:
                    task.status = "completed_with_errors"
                    task.error_message = f"{failed} chapters failed"
                db.commit()

            return {
                "success": True,
                "total_chapters": len(chapters),
                "successful": successful,
                "failed": failed,
                "results": results
            }

        except Exception as e:
            logger.error(f"Error processing story {story_id}: {e}")
            if task:
                task.status = "failed"
                task.error_message = str(e)
                db.commit()
            return {"success": False, "error": str(e)}

    async def process_merged_content(
        self,
        story_id: str,
        db: Session,
        voice_code: str = "hn_female_ngochuyen_full_48k-fhg",
        audio_type: str = "mp3",
        bitrate: int = 128,
        speed: float = 1.0,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """
        Process merged content of a story to audio (single TTS request)

        Args:
            story_id: Story ID to process
            db: Database session
            voice_code: Voice to use
            audio_type: Output format
            bitrate: Audio quality
            speed: Speaking speed
            progress_callback: Optional callback for progress

        Returns:
            Dictionary with processing results
        """
        try:
            # Get story from database
            story = db.query(models.Story).filter(models.Story.id == story_id).first()
            if not story:
                return {"success": False, "error": "Story not found"}

            # Get merged content
            if not story.merged_content or story.merged_content.strip() == "":
                return {"success": False, "error": "No merged content found. Please edit content in Grammar step first."}

            merged_content = story.merged_content.strip()
            logger.info(f"Processing merged content for story {story_id}, {len(merged_content)} chars")

            if progress_callback:
                progress_callback(f"Starting TTS for {len(merged_content)} characters...")

            # Call TTS API
            tts_result = await self.text_to_speech(
                text=merged_content,
                voice_code=voice_code,
                audio_type=audio_type,
                bitrate=bitrate,
                speed=speed
            )

            if not tts_result:
                return {"success": False, "error": "TTS API failed"}

            request_id = tts_result.get('request_id')
            if not request_id:
                return {"success": False, "error": "No request ID received"}

            logger.info(f"TTS request created: {request_id}")

            if progress_callback:
                progress_callback(f"Waiting for audio generation... (request_id: {request_id})")

            # Wait for audio to be ready
            audio_link = await self.get_audio_link(request_id)
            if not audio_link:
                return {"success": False, "error": "Could not get audio link", "request_id": request_id}

            logger.info(f"Audio ready: {audio_link}")

            # Define output path
            story_folder = story.title.replace(' ', '_').replace('/', '_') if story.title else f"story_{story_id}"
            output_dir = Path(settings.STORAGE_PATH) / "audio" / story_folder
            output_path = output_dir / f"merged_audio.{audio_type}"

            if progress_callback:
                progress_callback(f"Downloading audio...")

            # Download audio
            success = await self.download_audio(audio_link, str(output_path))
            if not success:
                return {"success": False, "error": "Failed to download audio", "request_id": request_id, "audio_link": audio_link}

            # Get file size
            file_size = os.path.getsize(output_path)

            # Deliver finished audio to the user's output folder (Downloads by
            # default). Everything reads audio by absolute path, so we store the
            # delivered path in the DB and downstream steps keep working.
            _story = db.query(models.Story).filter(models.Story.id == story_id).first()
            _name = safe_file_stem(_story.title if _story and _story.title else story_id, story_id)
            final_path = deliver_final(str(output_path), db, filename=f"{_name}.{audio_type}")

            # Save to MergedAudio table
            merged_audio = db.query(models.MergedAudio).filter(
                models.MergedAudio.story_id == story_id
            ).first()

            if merged_audio:
                # Update existing
                merged_audio.file_path = final_path
                merged_audio.file_size = file_size
                merged_audio.format = audio_type
            else:
                # Create new
                merged_audio = models.MergedAudio(
                    story_id=story_id,
                    file_path=final_path,
                    file_size=file_size,
                    format=audio_type
                )
                db.add(merged_audio)

            db.commit()

            logger.info(f"TTS completed for story {story_id}: {final_path}")

            return {
                "success": True,
                "story_id": story_id,
                "request_id": request_id,
                "audio_link": audio_link,
                "file_path": final_path,
                "file_size": file_size,
                "char_count": len(merged_content)
            }

        except Exception as e:
            logger.error(f"Error processing merged content for story {story_id}: {e}")
            return {"success": False, "error": str(e)}

    def get_available_voices(self) -> List[Dict]:
        """
        Get list of available voices

        Returns:
            List of voice options
        """
        # This is a static list, but could be fetched from API
        voices = [
            {
                "code": "hn_female_ngochuyen_full_48k-fhg",
                "name": "Ngoc Huyen",
                "gender": "female",
                "language": "vi-VN"
            },
            {
                "code": "hn_male_minhhoang_full_48k-fhg",
                "name": "Minh Hoang",
                "gender": "male",
                "language": "vi-VN"
            },
            {
                "code": "hn_female_thuminh_full_48k-fhg",
                "name": "Thu Minh",
                "gender": "female",
                "language": "vi-VN"
            },
            {
                "code": "hn_male_giahuy_full_48k-fhg",
                "name": "Gia Huy",
                "gender": "male",
                "language": "vi-VN"
            },
        ]
        return voices
