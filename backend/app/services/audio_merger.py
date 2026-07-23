"""
Audio Merger Service
Refactored from make_story/audio_merger_tool.py
Service for merging multiple audio files using FFmpeg
"""
import os
import re
import json
import subprocess
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Callable
from datetime import datetime

from sqlalchemy.orm import Session
from loguru import logger

from app import models
from app.config import settings
from app.services.output_delivery import deliver_final, safe_file_stem


class AudioMerger:
    """Service for merging audio files using FFmpeg"""

    # Supported audio formats
    SUPPORTED_FORMATS = ['.mp3', '.wav', '.ogg', '.flac', '.m4a', '.mp4', '.wma', '.aac']

    def __init__(self):
        """Initialize audio merger"""
        self.ffmpeg_available = self._check_ffmpeg()
        if not self.ffmpeg_available:
            logger.warning("FFmpeg not found. Audio merging will not work.")

    def _check_ffmpeg(self) -> bool:
        """Check if FFmpeg is installed"""
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def get_audio_duration(self, file_path: str) -> float:
        """
        Get duration of audio file using ffprobe

        Args:
            file_path: Path to audio file

        Returns:
            Duration in seconds, or 0 if error
        """
        if not self.ffmpeg_available:
            return 0

        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return float(data['format']['duration'])
        except Exception as e:
            logger.error(f"Error getting audio duration: {e}")
        return 0

    def _natural_sort_key(self, filename: str) -> List:
        """
        Natural sort key for file names with numbers

        Args:
            filename: File name to create sort key for

        Returns:
            List of sort components
        """
        parts = re.split(r'(\d+)', filename)
        return [int(part) if part.isdigit() else part.lower() for part in parts]

    def _get_codec(self, format_name: str) -> str:
        """
        Get appropriate codec for audio format

        Args:
            format_name: Audio format (mp3, aac, etc.)

        Returns:
            FFmpeg codec name
        """
        codecs = {
            'mp3': 'libmp3lame',
            'aac': 'aac',
            'm4a': 'aac',
            'ogg': 'libvorbis',
            'flac': 'flac',
            'wav': 'pcm_s16le'
        }
        return codecs.get(format_name.lower(), 'copy')

    async def merge_audio_files(
        self,
        input_files: List[str],
        output_path: str,
        format: str = 'mp3',
        bitrate: str = '192k',
        crossfade: int = 0,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """
        Merge multiple audio files into one

        Args:
            input_files: List of input file paths
            output_path: Output file path
            format: Output format (mp3, wav, etc.)
            bitrate: Output bitrate (e.g., '192k')
            crossfade: Crossfade duration in seconds (0 = no crossfade)
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with merge results
        """
        if not self.ffmpeg_available:
            return {
                "success": False,
                "error": "FFmpeg not installed"
            }

        if not input_files:
            return {
                "success": False,
                "error": "No input files provided"
            }

        # Filter out None values and validate
        input_files = [f for f in input_files if f is not None]
        if not input_files:
            return {
                "success": False,
                "error": "All input files are None"
            }

        # Validate all files exist
        missing_files = [f for f in input_files if not os.path.exists(f)]
        if missing_files:
            logger.error(f"Missing files: {missing_files}")
            return {
                "success": False,
                "error": f"Missing {len(missing_files)} audio file(s). Please check if TTS completed successfully."
            }

        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir:  # Only create if directory path is not empty
            os.makedirs(output_dir, exist_ok=True)

        logger.info(f"Output path: {output_path}")
        logger.info(f"Output directory: {output_dir}")

        # Sort files naturally (handling numbers in names)
        input_files.sort(key=lambda x: self._natural_sort_key(os.path.basename(x)))

        try:
            if progress_callback:
                progress_callback(f"Merging {len(input_files)} audio files...")

            if crossfade > 0 and len(input_files) > 1:
                # Complex merge with crossfade
                result = await self._merge_with_crossfade(
                    input_files, output_path, format, bitrate, crossfade
                )
            else:
                # Simple concatenation
                result = await self._merge_simple(
                    input_files, output_path, format, bitrate
                )

            if result["success"]:
                # Get output file info
                duration = self.get_audio_duration(output_path)
                file_size = os.path.getsize(output_path)

                result.update({
                    "duration": duration,
                    "file_size": file_size,
                    "output_path": output_path,
                    "input_count": len(input_files)
                })

                if progress_callback:
                    progress_callback(f"Successfully merged {len(input_files)} files")

            return result

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"Error merging audio files: {e}")
            logger.error(f"Traceback: {error_trace}")
            return {
                "success": False,
                "error": str(e) if str(e) else f"Unknown error: {type(e).__name__}"
            }

    async def _merge_simple(
        self,
        input_files: List[str],
        output_path: str,
        format: str,
        bitrate: str
    ) -> Dict:
        """
        Simple concatenation without crossfade

        Args:
            input_files: Input file paths
            output_path: Output file path
            format: Output format
            bitrate: Output bitrate

        Returns:
            Result dictionary
        """
        try:
            # Create temporary list file
            list_file = os.path.join(
                os.path.dirname(output_path) or '.',
                'temp_list.txt'
            )

            logger.info(f"Creating temp list file: {list_file}")

            # Write file list with absolute paths
            with open(list_file, 'w', encoding='utf-8') as f:
                for audio_file in input_files:
                    # Convert to absolute path
                    abs_path = os.path.abspath(audio_file)
                    # Escape single quotes
                    safe_path = abs_path.replace("'", "'\\''")
                    # Use forward slashes for FFmpeg compatibility
                    safe_path = safe_path.replace('\\', '/')
                    f.write(f"file '{safe_path}'\n")

            logger.info(f"Temp list file created with {len(input_files)} entries")

            # FFmpeg command
            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', list_file,
                '-c:a', self._get_codec(format),
                '-b:a', bitrate,
                output_path
            ]

            logger.info(f"Running FFmpeg command: {' '.join(cmd)}")

            # Run FFmpeg (using sync subprocess for Windows compatibility)
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=600  # 10 minutes timeout
            )

            if process.returncode == 0:
                logger.info("FFmpeg merge completed successfully")
                return {"success": True}
            else:
                error_msg = process.stderr.decode() if process.stderr else "No error message"
                logger.error(f"FFmpeg error (code {process.returncode}): {error_msg}")
                return {
                    "success": False,
                    "error": f"FFmpeg failed with code {process.returncode}: {error_msg[:200]}"
                }

        except Exception as e:
            import traceback
            logger.error(f"Error in _merge_simple: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": f"Merge error: {str(e)}"
            }
        finally:
            # Clean up temp file
            try:
                if 'list_file' in locals() and os.path.exists(list_file):
                    os.remove(list_file)
                    logger.info(f"Cleaned up temp file: {list_file}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file: {e}")

    async def _merge_with_crossfade(
        self,
        input_files: List[str],
        output_path: str,
        format: str,
        bitrate: str,
        crossfade: int
    ) -> Dict:
        """
        Merge with crossfade effect

        Args:
            input_files: Input file paths
            output_path: Output file path
            format: Output format
            bitrate: Output bitrate
            crossfade: Crossfade duration in seconds

        Returns:
            Result dictionary
        """
        # Build complex filter for crossfade
        filter_str = ""
        for i in range(len(input_files) - 1):
            if i == 0:
                filter_str += f"[0:a][1:a]acrossfade=d={crossfade}:c1=tri:c2=tri[a01];"
            else:
                prev = f"a{i-1:02d}{i:02d}" if i > 1 else "a01"
                curr = f"a{i:02d}{i+1:02d}"
                filter_str += f"[{prev}][{i+1}:a]acrossfade=d={crossfade}:c1=tri:c2=tri[{curr}];"

        # Final output label
        final_output = f"a{len(input_files)-2:02d}{len(input_files)-1:02d}" if len(input_files) > 2 else "a01"

        # Build FFmpeg command
        cmd = ['ffmpeg', '-y']
        for file in input_files:
            cmd.extend(['-i', file])
        cmd.extend([
            '-filter_complex', filter_str.rstrip(';'),
            '-map', f'[{final_output}]',
            '-c:a', self._get_codec(format),
            '-b:a', bitrate,
            output_path
        ])

        # Run FFmpeg (using sync subprocess for Windows compatibility)
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600  # 10 minutes timeout
        )

        if process.returncode == 0:
            return {"success": True}
        else:
            error_msg = process.stderr.decode() if process.stderr else "No error message"
            logger.error(f"FFmpeg crossfade error: {error_msg}")
            return {
                "success": False,
                "error": f"FFmpeg crossfade failed: {error_msg[:200]}"
            }

    async def merge_story_audio(
        self,
        story_id: str,
        task_id: str,
        db: Session,
        format: str = 'mp3',
        bitrate: str = '192k',
        crossfade: int = 0
    ) -> Dict:
        """
        Merge all audio files for a story

        Args:
            story_id: Story ID
            task_id: Task ID for progress tracking
            db: Database session
            format: Output format
            bitrate: Output bitrate
            crossfade: Crossfade duration

        Returns:
            Dictionary with merge results
        """
        try:
            # Get story info
            story = db.query(models.Story).filter(models.Story.id == story_id).first()
            if not story:
                return {"success": False, "error": "Story not found"}

            # Get all SUCCESSFUL audio files for the story (with valid file_path)
            audio_files = db.query(models.AudioFile).join(
                models.Chapter
            ).filter(
                models.Chapter.story_id == story_id,
                models.AudioFile.status == 'success',
                models.AudioFile.file_path.isnot(None)
            ).order_by(
                models.Chapter.chapter_number
            ).all()

            if not audio_files:
                return {"success": False, "error": "No successful audio files found. Please complete TTS processing first."}

            # Update task
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                task.status = "running"
                task.total_items = len(audio_files)
                db.commit()

            # Get file paths and validate
            input_paths = [af.file_path for af in audio_files if af.file_path]

            if not input_paths:
                return {"success": False, "error": "No valid audio file paths found"}

            # Log info
            logger.info(f"Merging {len(input_paths)} audio files for story {story_id}")
            for i, path in enumerate(input_paths, 1):
                logger.info(f"  {i}. {path}")

            # Define output path
            story_folder = story.title.replace(' ', '_')
            output_dir = Path(settings.STORAGE_PATH) / "merged" / story_folder
            output_path = output_dir / f"{story_folder}_complete.{format}"

            # Merge audio files
            result = await self.merge_audio_files(
                input_files=input_paths,
                output_path=str(output_path),
                format=format,
                bitrate=bitrate,
                crossfade=crossfade,
                progress_callback=lambda msg: logger.info(msg)
            )

            if result["success"]:
                # Deliver finished audio to the user's output folder (Downloads default)
                _name = safe_file_stem(story.title if story and story.title else story_id, story_id)
                final_path = deliver_final(str(output_path), db, filename=f"{_name}.{format}", subfolder=_name)

                # Save merged audio record
                merged_audio = models.MergedAudio(
                    story_id=story_id,
                    file_path=final_path,
                    duration=result.get("duration", 0),
                    format=format,
                    # Note: bitrate and source_count fields not in MergedAudio model
                    # bitrate=bitrate,
                    total_chapters=len(input_paths),  # Use total_chapters instead of source_count
                    file_size=result.get("file_size", 0)
                )
                db.add(merged_audio)

                # Update task
                if task:
                    task.status = "completed"
                    task.progress = 100
                    task.completed_items = len(audio_files)

                db.commit()

                return {
                    "success": True,
                    "output_path": final_path,
                    "duration": result.get("duration", 0),
                    "file_size": result.get("file_size", 0),
                    "source_count": len(input_paths)
                }
            else:
                # Update task with error
                if task:
                    task.status = "failed"
                    task.error_message = result.get("error", "Unknown error")
                    db.commit()

                return result

        except Exception as e:
            logger.error(f"Error merging story audio: {e}")
            if task:
                task = db.query(models.Task).filter(models.Task.id == task_id).first()
                if task:
                    task.status = "failed"
                    task.error_message = str(e)
                    db.commit()
            return {"success": False, "error": str(e)}

    def validate_audio_files(self, file_paths: List[str]) -> Dict:
        """
        Validate that all audio files exist and are valid

        Args:
            file_paths: List of file paths to validate

        Returns:
            Dictionary with validation results
        """
        missing_files = []
        invalid_files = []
        valid_files = []

        for path in file_paths:
            if not os.path.exists(path):
                missing_files.append(path)
            else:
                ext = os.path.splitext(path)[1].lower()
                if ext not in self.SUPPORTED_FORMATS:
                    invalid_files.append(path)
                else:
                    # Check if file is actually readable
                    duration = self.get_audio_duration(path)
                    if duration > 0:
                        valid_files.append(path)
                    else:
                        invalid_files.append(path)

        return {
            "valid": len(missing_files) == 0 and len(invalid_files) == 0,
            "valid_files": valid_files,
            "missing_files": missing_files,
            "invalid_files": invalid_files,
            "total_files": len(file_paths)
        }

    def estimate_merge_time(self, file_count: int, total_duration: float) -> float:
        """
        Estimate time required to merge audio files

        Args:
            file_count: Number of files to merge
            total_duration: Total duration in seconds

        Returns:
            Estimated time in seconds
        """
        # Rough estimate: about 10% of total duration for simple merge
        # Add overhead for file operations
        base_time = total_duration * 0.1
        overhead = file_count * 0.5  # 0.5 seconds per file
        return base_time + overhead