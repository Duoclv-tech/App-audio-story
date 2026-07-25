"""
Video Processor Service
Creates video from background clips + audio using FFmpeg
Ported from tool_split_bg_video/random_video_into_folder.py

Flow:
1. Select video clips to match audio duration (order: "shuffle" random by
   default, or "name" filename A→Z; controlled by clip_order)
2. Copy selected clips into a temp folder (named by timestamp, numbered 0001_xxx)
3. Stale temp folders from previous runs are removed first (no reuse) — the
   source folder is re-scanned every render
4. Concat all clips in temp folder using ffmpeg concat demuxer (stable, no file limit)
5. Speed up audio
6. Merge audio + video
7. Retry up to 2 times on failure
"""
import math
import os
import json
import random
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple
from loguru import logger

from sqlalchemy.orm import Session
from app import models
from app.config import settings
from app.services.output_delivery import deliver_final, safe_file_stem

VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v'}

_NVENC_CACHED: Optional[bool] = None

AD_MAX_JITTER = 0.05
AD_MAX_ZOOM = 1.15
AD_RATE_EPSILON = 1e-3

# Frontend exposes "crossfade" but FFmpeg's xfade has no transition by that
# name — `fade` is already a luminance crossfade. Map UI names to xfade ones.
_XFADE_NAME_MAP: Dict[str, str] = {
    "crossfade": "fade",
}


class VideoProcessor:
    """Service for creating video from background clips + audio"""

    def __init__(self):
        self.ffmpeg_available = self._check_ffmpeg()
        if not self.ffmpeg_available:
            logger.warning("FFmpeg not found. Video processing will not work.")
        self.nvenc_available = self._check_nvenc()
        if self.nvenc_available:
            logger.info("NVENC GPU encoding available (h264_nvenc)")
        else:
            logger.info("NVENC not available, using CPU encoding (libx264)")

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

    def _check_nvenc(self) -> bool:
        # ffmpeg may list h264_nvenc even when libcuda.so.1 isn't installed, so
        # we try a real 1-frame encode to confirm runtime support. Memoized
        # because the driver state doesn't change for the lifetime of the
        # process and VideoProcessor() is constructed per-request.
        global _NVENC_CACHED
        if _NVENC_CACHED is not None:
            return _NVENC_CACHED
        if not self.ffmpeg_available:
            _NVENC_CACHED = False
            return False
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            if 'h264_nvenc' not in result.stdout:
                _NVENC_CACHED = False
                return False
        except Exception:
            _NVENC_CACHED = False
            return False
        try:
            null_path = 'NUL' if os.name == 'nt' else '/dev/null'
            r = subprocess.run([
                'ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'color=black:s=256x256:d=0.1',
                '-frames:v', '1',
                '-c:v', 'h264_nvenc',
                '-f', 'null', null_path,
            ], capture_output=True, timeout=10)
            _NVENC_CACHED = r.returncode == 0
        except Exception:
            _NVENC_CACHED = False
        return _NVENC_CACHED

    def _get_encode_args(self) -> list:
        """Get encoder arguments: NVENC if available, otherwise libx264"""
        if self.nvenc_available:
            return ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '23', '-b:v', '0']
        return ['-c:v', 'libx264', '-preset', 'medium', '-crf', '23']

    def get_media_duration(self, file_path: str) -> float:
        """Get duration of media file using ffprobe"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet',
                '-print_format', 'json',
                '-show_format', '-show_streams',
                str(file_path)
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace'
            )
            if result.returncode != 0:
                return 0

            data = json.loads(result.stdout)

            # Prefer video stream duration
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video' and 'duration' in stream:
                    d = float(stream['duration'])
                    if d > 0:
                        return d

            # Fallback to format duration
            if 'format' in data and 'duration' in data['format']:
                d = float(data['format']['duration'])
                if d > 0:
                    return d
        except Exception as e:
            logger.error(f"Error getting media duration for {file_path}: {e}")
        return 0

    def has_audio_stream(self, file_path: str) -> bool:
        """Return True if the media file contains at least one audio stream."""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_streams', '-select_streams', 'a',
                str(file_path),
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace'
            )
            if result.returncode != 0:
                return False
            data = json.loads(result.stdout or '{}')
            return bool(data.get('streams'))
        except Exception:
            return False

    def get_video_dimensions(self, file_path: str) -> tuple:
        """Get width and height of a video file"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams',
                str(file_path)
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        w = int(stream.get('width', 0))
                        h = int(stream.get('height', 0))
                        if w > 0 and h > 0:
                            return (w, h)
        except Exception as e:
            logger.error(f"Error getting video dimensions for {file_path}: {e}")
        return (0, 0)

    def get_all_videos_in_folder(self, folder: str, order: str = "shuffle") -> List[Dict]:
        """Scan folder for video files with durations.

        order: "shuffle" (random — used by main pipeline) or "name" (sorted —
        used by preview, which plays clips in deterministic order).

        ffprobes are run in parallel — large folders (~hundreds of clips) used
        to take seconds of mostly-idle wall time when probed serially.
        """
        folder_path = Path(folder)
        files = [f for f in folder_path.iterdir()
                 if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS]

        if order == "name":
            files.sort()
        else:
            random.shuffle(files)

        if not files:
            return []

        def probe(file: Path):
            try:
                d = self.get_media_duration(str(file))
                if d > 0:
                    return {'path': str(file), 'duration': d, 'name': file.name}
            except Exception as e:
                logger.warning(f"Skipping {file.name}: {e}")
            return None

        with ThreadPoolExecutor(max_workers=min(8, len(files))) as ex:
            results = list(ex.map(probe, files))

        return [r for r in results if r is not None]

    def copy_to_temp_folder(self, selected: List[Dict], temp_folder: str) -> List[str]:
        """
        Copy selected videos into temp folder with numbered names.
        Returns list of copied file paths in order.
        """
        os.makedirs(temp_folder, exist_ok=True)

        copied_paths = []
        for i, video in enumerate(selected, 1):
            src = video['path']
            ext = Path(src).suffix
            dst_name = f"{i:04d}_{Path(src).name}"
            dst = os.path.join(temp_folder, dst_name)
            shutil.copy2(src, dst)
            copied_paths.append(dst)
            logger.info(f"  [{i}/{len(selected)}] Copied {dst_name}")

        total_size = sum(os.path.getsize(p) for p in copied_paths)
        logger.info(f"Copied {len(copied_paths)} files to {temp_folder} ({total_size / (1024*1024):.1f} MB)")
        return copied_paths

    def get_temp_folder_videos(self, temp_folder: str) -> List[str]:
        """Get sorted video files from existing temp folder"""
        folder = Path(temp_folder)
        if not folder.exists():
            return []

        files = sorted([
            str(f) for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ])
        return files

    def validate_video_folder(self, folder: str) -> Dict:
        """Validate that folder exists and contains videos"""
        folder_path = Path(folder)

        if not folder_path.exists():
            return {"valid": False, "video_count": 0, "total_duration": 0,
                    "total_duration_formatted": "", "error": f"Folder not found: {folder}"}

        if not folder_path.is_dir():
            return {"valid": False, "video_count": 0, "total_duration": 0,
                    "total_duration_formatted": "", "error": f"Not a directory: {folder}"}

        videos = self.get_all_videos_in_folder(folder)
        if not videos:
            return {"valid": False, "video_count": 0, "total_duration": 0,
                    "total_duration_formatted": "", "error": "No video files found in folder"}

        total_duration = sum(v['duration'] for v in videos)
        return {
            "valid": True,
            "video_count": len(videos),
            "total_duration": total_duration,
            "total_duration_formatted": self._format_duration(total_duration),
            "error": None
        }

    def _format_duration(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    def concatenate_videos_from_folder(
        self,
        video_paths: List[str],
        output_path: str,
        resolution: str = "1920x1080",
        keep_audio: bool = False,
        transitions_pool: Optional[List[str]] = None,
        transition_duration: float = 0.5,
        flip_mode: str = "none",
        clip_speed_jitter: float = 0.0,
        ad_color_zoom_filter: str = "",
        max_duration: Optional[float] = None,
    ) -> Dict:
        """
        Concatenate videos using concat filter or xfade chain.
        Handles different fps, codec, resolution automatically.
        Processes in batches of BATCH_SIZE to avoid ffmpeg command line limits.

        keep_audio: when True, also concatenate audio tracks from each clip.
        Inputs lacking audio get a silent track of matching duration.

        transitions_pool: when non-empty, build an xfade chain instead of plain
        concat. A random effect is sampled from the pool for every junction
        (n-1 transitions for n clips), so the same pool drives every clip — not
        just the first len(pool) clips.
        """
        if not video_paths:
            return {"success": False, "error": "No videos to concatenate"}

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        width, height = resolution.split('x')
        BATCH_SIZE = 50

        if len(video_paths) <= BATCH_SIZE:
            return self._concat_filter(
                video_paths, output_path, width, height, keep_audio,
                transitions_pool=transitions_pool,
                transition_duration=transition_duration,
                flip_mode=flip_mode,
                clip_speed_jitter=clip_speed_jitter,
                ad_color_zoom_filter=ad_color_zoom_filter,
                max_duration=max_duration,
            )

        # Process in batches for large numbers of files
        batch_dir = os.path.join(os.path.dirname(output_path), "_batches")
        os.makedirs(batch_dir, exist_ok=True)
        batch_outputs = []

        for batch_idx in range(0, len(video_paths), BATCH_SIZE):
            batch = video_paths[batch_idx:batch_idx + BATCH_SIZE]
            batch_num = batch_idx // BATCH_SIZE + 1
            batch_out = os.path.join(batch_dir, f"batch_{batch_num:03d}.mp4")

            logger.info(f"Processing batch {batch_num} ({len(batch)} clips)...")
            result = self._concat_filter(
                batch, batch_out, width, height, keep_audio,
                transitions_pool=transitions_pool,
                transition_duration=transition_duration,
                flip_mode=flip_mode,
                clip_speed_jitter=clip_speed_jitter,
                ad_color_zoom_filter=ad_color_zoom_filter,
            )
            if not result["success"]:
                return result
            batch_outputs.append(batch_out)

        # Concat all batches (same format now, use demuxer).
        # Anti-detection per-clip ops only run inside batches; cross-batch
        # concat is plain (clips already flipped/jittered in their batch).
        if len(batch_outputs) == 1:
            shutil.move(batch_outputs[0], output_path)
            return {"success": True}

        logger.info(f"Merging {len(batch_outputs)} batches...")
        result = self._concat_filter(
            batch_outputs, output_path, width, height, keep_audio,
            transitions_pool=transitions_pool,
            transition_duration=transition_duration,
            max_duration=max_duration,
        )

        # Cleanup batches
        try:
            shutil.rmtree(batch_dir)
        except Exception:
            pass

        return result

    def _concat_filter(
        self,
        video_paths: List[str],
        output_path: str,
        width: str,
        height: str,
        keep_audio: bool = False,
        transitions_pool: Optional[List[str]] = None,
        transition_duration: float = 0.5,
        flip_mode: str = "none",
        clip_speed_jitter: float = 0.0,
        ad_color_zoom_filter: str = "",
        max_duration: Optional[float] = None,
    ) -> Dict:
        """
        Concat using filter_complex.
        Each input is scaled + fps normalized, then concatenated.

        When keep_audio=True, each input's audio is normalized to a common
        sample rate / layout and concatenated. Inputs without an audio stream
        get a silent track injected via anullsrc to keep the concat aligned.

        When transitions_pool is non-empty and there are >=2 clips and every
        clip is at least 2*transition_duration long, a chained xfade is built
        instead of plain concat. A random effect is sampled per junction so
        the pool drives every clip, not just the first len(pool).
        """
        n = len(video_paths)

        # Decide whether to use xfade chain
        use_xfade = (
            bool(transitions_pool)
            and n >= 2
            and transition_duration > 0
        )

        durations: List[float] = []
        if use_xfade:
            durations = [self.get_media_duration(p) or 0.0 for p in video_paths]
            # xfade needs each clip to overlap by transition_duration on at
            # least one side; middle clips overlap on both sides. Require
            # 2*td as a safe lower bound across all positions.
            min_required = 2 * transition_duration
            too_short = [
                (i, d) for i, d in enumerate(durations) if d < min_required
            ]
            if too_short:
                logger.warning(
                    f"Disabling xfade: {len(too_short)} clip(s) shorter than "
                    f"2*transition_duration ({min_required:.2f}s); falling back to plain concat"
                )
                use_xfade = False

        # Probe per-clip audio presence when caller asks to keep audio.
        audio_flags: List[bool] = []
        if keep_audio:
            audio_flags = [self.has_audio_stream(p) for p in video_paths]
            if not any(audio_flags):
                # No clip has audio — fall back to muted concat to avoid empty amix.
                logger.warning("keep_audio requested but no clip has audio; falling back to muted concat")
                keep_audio = False

        # Pre-compute per-clip flip flag and speed rate for the anti-detection
        # options. Tracking rates lets xfade offsets stay correct when clips
        # are stretched/squeezed individually.
        clip_flips: List[bool] = []
        clip_rates: List[float] = []
        jitter = max(0.0, min(AD_MAX_JITTER, float(clip_speed_jitter)))
        for _ in range(n):
            if flip_mode == "all":
                clip_flips.append(True)
            elif flip_mode == "random":
                clip_flips.append(random.random() < 0.5)
            else:
                clip_flips.append(False)
            if jitter > 0:
                clip_rates.append(1.0 + random.uniform(-jitter, jitter))
            else:
                clip_rates.append(1.0)

        filter_parts = []
        for i in range(n):
            extras = ""
            if clip_flips[i]:
                extras += ",hflip"
            if abs(clip_rates[i] - 1.0) > AD_RATE_EPSILON:
                extras += f",setpts=PTS/{clip_rates[i]:.4f}"
            extras += ad_color_zoom_filter
            filter_parts.append(
                f'[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,'
                f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                f'fps=30,format=yuv420p{extras}[v{i}];'
            )

        if keep_audio:
            # Generate a silent source we can substitute when a clip lacks audio.
            silence_idx = n  # next input index after all video inputs
            for i in range(n):
                # When clip_speed_jitter is active, audio must atempo by the
                # same rate as video setpts, otherwise A/V drift.
                a_jitter = ""
                if abs(clip_rates[i] - 1.0) > AD_RATE_EPSILON:
                    a_jitter = f",atempo={clip_rates[i]:.4f}"
                if audio_flags[i]:
                    filter_parts.append(
                        f'[{i}:a]aresample=44100,'
                        f'aformat=sample_fmts=fltp:channel_layouts=stereo{a_jitter}[a{i}];'
                    )
                else:
                    # Pull from the shared silent source; trim to clip duration.
                    dur = (
                        durations[i]
                        if durations
                        else (self.get_media_duration(video_paths[i]) or 0.0)
                    )
                    filter_parts.append(
                        f'[{silence_idx}:a]atrim=duration={dur:.3f},asetpts=PTS-STARTPTS,'
                        f'aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo{a_jitter}[a{i}];'
                    )

        if use_xfade:
            chosen: List[str] = []
            chain_v = 'v0'
            chain_a = 'a0' if keep_audio else None
            # Effective duration shrinks/grows when setpts/atempo is applied.
            cumulative = durations[0] / clip_rates[0]
            for i in range(1, n):
                raw = random.choice(transitions_pool)
                effect = _XFADE_NAME_MAP.get(raw, raw)
                chosen.append(effect)

                offset = max(0.0, cumulative - transition_duration)
                is_last = (i == n - 1)
                v_out = 'outv' if is_last else f'vx{i}'
                filter_parts.append(
                    f'[{chain_v}][v{i}]xfade=transition={effect}:'
                    f'duration={transition_duration:.3f}:offset={offset:.3f}[{v_out}];'
                )
                chain_v = v_out

                if keep_audio:
                    a_out = 'outa' if is_last else f'ax{i}'
                    filter_parts.append(
                        f'[{chain_a}][a{i}]acrossfade=d={transition_duration:.3f}[{a_out}];'
                    )
                    chain_a = a_out

                cumulative += (durations[i] / clip_rates[i]) - transition_duration

            logger.info(
                f"xfade chain: {n} clips, td={transition_duration}s, "
                f"{len(chosen)} transitions picked from pool of "
                f"{len(transitions_pool)} ({chosen})"
            )
        elif keep_audio:
            concat_inputs = ''.join(f'[v{i}][a{i}]' for i in range(n))
            filter_parts.append(f'{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]')
        else:
            concat_inputs = ''.join(f'[v{i}]' for i in range(n))
            filter_parts.append(f'{concat_inputs}concat=n={n}:v=1:a=0[outv]')

        filter_complex = ''.join(filter_parts).rstrip(';')

        cmd = ['ffmpeg', '-y']
        for vpath in video_paths:
            cmd.extend(['-i', vpath])
        if keep_audio and not all(audio_flags):
            # Single anullsrc input feeds every silent placeholder above.
            cmd.extend([
                '-f', 'lavfi',
                '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
            ])
        cmd.extend([
            '-filter_complex', filter_complex,
            '-map', '[outv]',
        ])
        if keep_audio:
            cmd.extend(['-map', '[outa]'])
        cmd.extend(self._get_encode_args())
        if keep_audio:
            cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
        # Bound output duration so ffmpeg stops encoding once it has produced
        # exactly `max_duration` seconds — avoids re-encoding the trailing
        # excess of the last clip just to throw it away.
        if max_duration is not None and max_duration > 0:
            cmd.extend(['-t', f'{max_duration:.3f}'])
        cmd.append(output_path)

        logger.info(
            f"Running concat filter: {n} videos -> {output_path} "
            f"(keep_audio={keep_audio}, xfade={use_xfade})"
        )
        process = subprocess.run(cmd, capture_output=True, timeout=14400)  # 4 hour timeout

        if process.returncode == 0:
            return {"success": True}
        else:
            error_msg = process.stderr.decode(errors='replace')[-500:]
            return {"success": False, "error": f"FFmpeg concat filter failed: {error_msg}"}

    def speed_up_audio(self, input_path: str, output_path: str, speed: float = 1.07) -> Dict:
        """Speed up audio using atempo filter"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-filter:a', f'atempo={speed}',
            '-vn',
            output_path
        ]

        logger.info(f"Speeding up audio: {speed}x")
        process = subprocess.run(cmd, capture_output=True, timeout=3600)

        if process.returncode == 0:
            return {"success": True}
        else:
            error_msg = process.stderr.decode(errors='replace')[-500:]
            return {"success": False, "error": f"Audio speed up failed: {error_msg}"}

    def merge_audio_video(self, video_path: str, audio_path: str, output_path: str) -> Dict:
        """Merge audio and video tracks, using -shortest to match durations.

        If the background video already carries an audio track (concat ran with
        keep_audio=True), mix it with the main audio so both play together.
        Otherwise just attach the main audio.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        bg_has_audio = self.has_audio_stream(video_path)

        cmd = ['ffmpeg', '-y', '-i', video_path, '-i', audio_path]

        if bg_has_audio:
            cmd.extend([
                '-filter_complex',
                '[0:a][1:a]amix=inputs=2:duration=shortest:dropout_transition=0[aout]',
                '-map', '0:v', '-map', '[aout]',
            ])
        else:
            cmd.extend(['-map', '0:v', '-map', '1:a'])

        cmd.extend([
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            output_path,
        ])

        logger.info(f"Merging audio + video (bg_audio={bg_has_audio})")
        process = subprocess.run(cmd, capture_output=True, timeout=3600)

        if process.returncode == 0:
            return {"success": True}
        else:
            error_msg = process.stderr.decode(errors='replace')[-500:]
            return {"success": False, "error": f"Audio-video merge failed: {error_msg}"}

    def mix_background_music(
        self,
        voice_path: str,
        bgm_path: str,
        output_path: str,
        *,
        volume: float = 0.12,
        loop: bool = True,
        ducking: bool = True,
        fade: float = 2.0,
    ) -> Dict:
        """Mix a background-music track under the main narration.

        The output has exactly the narration's duration (``duration=first`` on
        amix, plus a hard ``-t`` clamp). When ``loop`` is set the music input is
        stream-looped so a short track fills a long narration; when it is longer
        it is simply cut at the narration's end.

        ``ducking`` runs the music through ``sidechaincompress`` keyed off the
        voice so the music dips automatically whenever narration is present, then
        recovers in the gaps. ``normalize=0`` on amix keeps the voice at full
        level (amix otherwise attenuates every input by 1/n).
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        voice_dur = self.get_media_duration(voice_path)
        if voice_dur <= 0:
            return {"success": False, "error": "Cannot determine narration duration for BGM mix"}

        vol = max(0.0, min(1.0, volume))

        cmd = ['ffmpeg', '-y', '-i', voice_path]
        if loop:
            cmd += ['-stream_loop', '-1']
        cmd += ['-i', bgm_path]

        # Build the music-processing chain: volume, then optional fades.
        bgm_chain = [f'volume={vol:.4f}']
        if fade > 0:
            bgm_chain.append(f'afade=t=in:st=0:d={fade:.3f}')
            fade_out_start = max(0.0, voice_dur - fade)
            bgm_chain.append(f'afade=t=out:st={fade_out_start:.3f}:d={fade:.3f}')
        bgm_chain_str = ','.join(bgm_chain)

        if ducking:
            filter_complex = (
                f'[1:a]{bgm_chain_str}[bgmv];'
                f'[bgmv][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bgmd];'
                f'[0:a][bgmd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]'
            )
        else:
            filter_complex = (
                f'[1:a]{bgm_chain_str}[bgmv];'
                f'[0:a][bgmv]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]'
            )

        cmd += [
            '-filter_complex', filter_complex,
            '-map', '[aout]',
            '-t', f'{voice_dur:.3f}',
            '-c:a', 'libmp3lame', '-b:a', '192k',
            output_path,
        ]

        logger.info(f"Mixing BGM (vol={vol}, loop={loop}, ducking={ducking}, fade={fade}) -> {output_path}")
        process = subprocess.run(cmd, capture_output=True, timeout=3600)

        if process.returncode == 0:
            return {"success": True}
        else:
            error_msg = process.stderr.decode(errors='replace')[-500:]
            return {"success": False, "error": f"BGM mix failed: {error_msg}"}

    def _maybe_mix_bgm(
        self,
        sped_audio_path: str,
        output_dir: str,
        bgm_path: Optional[str],
        bgm_volume: float,
        bgm_loop: bool,
        bgm_ducking: bool,
        bgm_fade: float,
    ) -> Tuple[str, Optional[str]]:
        """Mix BGM into the (already sped-up) narration if a valid BGM path is set.

        Returns ``(path, warning)``: ``path`` is what the rest of the pipeline
        should treat as the main audio (the mixed file when BGM applied,
        otherwise the untouched ``sped_audio_path``); ``warning`` is a
        user-facing message when a BGM was configured but couldn't be mixed
        (None otherwise). The render itself is skipped-not-aborted on failure,
        but the caller is expected to surface ``warning`` rather than silently
        deliver a video missing the music the user asked for.
        """
        if not bgm_path or not os.path.exists(bgm_path):
            return sped_audio_path, None
        mixed_path = os.path.join(output_dir, "audio_with_bgm.mp3")
        res = self.mix_background_music(
            sped_audio_path, bgm_path, mixed_path,
            volume=bgm_volume, loop=bgm_loop, ducking=bgm_ducking, fade=bgm_fade,
        )
        if res.get("success"):
            logger.info(f"BGM mixed into narration -> {mixed_path}")
            return mixed_path, None
        warning = f"Không trộn được nhạc nền ({res.get('error')}); video dùng audio gốc không có nhạc nền."
        logger.warning(warning)
        return sped_audio_path, warning

    def trim_video(self, input_path: str, output_path: str, duration: float) -> Dict:
        """Trim video to exact duration"""
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-t', str(duration),
            '-c', 'copy',
            output_path
        ]

        logger.info(f"Trimming video to {self._format_duration(duration)}")
        process = subprocess.run(cmd, capture_output=True, timeout=3600)

        if process.returncode == 0:
            return {"success": True}
        else:
            error_msg = process.stderr.decode(errors='replace')[-500:]
            return {"success": False, "error": f"Video trim failed: {error_msg}"}

    def overlay_on_banner(
        self,
        video_path: str,
        banner_path: str,
        output_path: str,
        resolution: str = "1920x1080",
        duration: float = 0,
        video_scale: float = 0.85,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        scale_x: Optional[float] = None,
        scale_y: Optional[float] = None
    ) -> Dict:
        """Overlay video on top of a banner image background.
        Banner scales to full resolution. The video is scaled to
        scale_x * frame_width by scale_y * frame_height — independent per
        axis, so the clip can be stretched (aspect-distorted) to any size.
        When scale_x/scale_y are omitted both fall back to video_scale
        (uniform). It is centered by default; offset_x/offset_y (fraction of
        frame, 0 = centered) shift it horizontally/vertically."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        width, height = resolution.split('x')
        # Independent per-axis scale; fall back to the uniform video_scale.
        sx = video_scale if scale_x is None else scale_x
        sy = video_scale if scale_y is None else scale_y
        sx = max(0.1, min(3.0, sx))
        sy = max(0.1, min(3.0, sy))
        # Even dimensions keep yuv420 encoders happy.
        vid_w = max(2, int(int(width) * sx) & ~1)
        vid_h = max(2, int(int(height) * sy) & ~1)
        # Position = centered + offset (offset as a fraction of the full frame).
        # W/H are the banner (background) dimensions in the overlay filter.
        # Clamp defensively: the -0.5..0.5 bound is otherwise enforced only by the
        # frontend drag handler, so a stale/hand-edited config or a direct API
        # caller could otherwise push the clip entirely off-frame.
        offset_x = max(-0.5, min(0.5, offset_x))
        offset_y = max(-0.5, min(0.5, offset_y))
        pos_x = f"(W-w)/2+({offset_x:.5f})*W"
        pos_y = f"(H-h)/2+({offset_y:.5f})*H"

        filter_complex = (
            f"[0:v]scale={width}:{height},setsar=1[bg];"
            f"[1:v]scale={vid_w}:{vid_h},setsar=1[vid];"
            f"[bg][vid]overlay={pos_x}:{pos_y}:shortest=1[outv]"
        )

        cmd = ['ffmpeg', '-y', '-loop', '1', '-i', banner_path]
        if self.nvenc_available:
            cmd.extend(['-hwaccel', 'auto'])
        cmd.extend([
            '-i', video_path,
            '-filter_complex', filter_complex,
            '-map', '[outv]',
        ])
        # Pass through the source video's audio if present, so keep_audio mode
        # can mix it later in merge_audio_video.
        bg_has_audio = self.has_audio_stream(video_path)
        if bg_has_audio:
            cmd.extend(['-map', '1:a', '-c:a', 'aac', '-b:a', '192k'])
        cmd.extend(self._get_encode_args())
        if duration > 0:
            cmd.extend(['-t', str(duration)])
        cmd.append(output_path)

        logger.info(f"Overlaying video on banner: {banner_path}")
        process = subprocess.run(cmd, capture_output=True, timeout=7200)

        if process.returncode == 0:
            return {"success": True}
        else:
            error_msg = process.stderr.decode(errors='replace')[-500:]
            return {"success": False, "error": f"Banner overlay failed: {error_msg}"}

    def _run_ffmpeg_tracked(
        self,
        cmd: List[str],
        task,
        db,
        progress_start: int,
        progress_end: int,
        total_duration: float,
        timeout: int = 7200,
    ) -> Dict:
        """Run FFmpeg with real-time progress updates via -progress pipe:1.
        Streams out_time_us from stdout to update task.progress between start and end."""
        tracked_cmd = list(cmd[:-1]) + ['-progress', 'pipe:1', '-nostats', cmd[-1]]
        try:
            proc = subprocess.Popen(tracked_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            return {"success": False, "error": str(e)}

        stderr_buf: List[bytes] = []

        def _drain_stderr():
            for line in proc.stderr:
                stderr_buf.append(line)

        threading.Thread(target=_drain_stderr, daemon=True).start()

        deadline = time.monotonic() + timeout
        last_pct = progress_start
        try:
            for raw in proc.stdout:
                if time.monotonic() > deadline:
                    proc.kill()
                    return {"success": False, "error": "FFmpeg timeout"}
                line = raw.decode(errors='replace').strip()
                if line.startswith('out_time_us=') and total_duration > 0 and task:
                    val = line.split('=', 1)[1]
                    # ffmpeg emits N/A before first frame is encoded
                    if val == 'N/A':
                        continue
                    try:
                        us = int(val)
                        ratio = min(max(us / (total_duration * 1_000_000), 0.0), 0.99)
                        new_pct = progress_start + int(ratio * (progress_end - progress_start))
                        if new_pct > last_pct:
                            task.progress = new_pct
                            db.commit()
                            last_pct = new_pct
                    except (ValueError, ZeroDivisionError):
                        pass
        finally:
            proc.wait()

        if proc.returncode == 0:
            return {"success": True}
        error_msg = b''.join(stderr_buf).decode(errors='replace')[-500:]
        return {"success": False, "error": error_msg}

    def apply_overlay(self, input_path: str, output_path: str, opacity: float, resolution: str,
                      task=None, db=None, progress_start: int = 0, progress_end: int = 100) -> Dict:
        """Apply a black translucent overlay on top of video to darken it."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        width, height = resolution.split('x')
        filter_complex = (
            f"color=c=black@{opacity:.2f}:s={width}x{height}:r=30[ov];"
            f"[0:v][ov]overlay=format=auto:shortest=1[out]"
        )
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-filter_complex', filter_complex,
            '-map', '[out]', '-map', '0:a',
            '-c:a', 'copy',
        ]
        cmd.extend(self._get_encode_args())
        cmd.append(output_path)
        logger.info(f"Applying overlay opacity={opacity:.2f}")
        if task:
            return self._run_ffmpeg_tracked(cmd, task, db, progress_start, progress_end,
                                            self.get_media_duration(input_path))
        process = subprocess.run(cmd, capture_output=True, timeout=7200)
        if process.returncode == 0:
            return {"success": True}
        error_msg = process.stderr.decode(errors='replace')[-500:]
        return {"success": False, "error": f"Overlay failed: {error_msg}"}

    def apply_watermark(
        self,
        input_path: str,
        output_path: str,
        watermark_path: str,
        x: float,
        y: float,
        w: int,
        h: int,
        shape: str,
        opacity: float,
        resolution: str,
        task=None,
        db=None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> Dict:
        """Overlay a watermark/logo image at free position (center x,y in 0..1)
        with absolute size w x h px, optionally cropped to a shape (circle, rounded,
        star, sun)."""
        from app.services.shape_masks import get_mask_path

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Clamp x,y to keep watermark roughly inside frame; center-based
        cx = max(0.0, min(1.0, x))
        cy = max(0.0, min(1.0, y))
        # Clamp w/h to a reasonable range, ensure even pixels
        tw = max(16, min(int(w), 4096)) // 2 * 2
        th = max(16, min(int(h), 4096)) // 2 * 2
        pos = f"main_w*{cx:.4f}-overlay_w/2:main_h*{cy:.4f}-overlay_h/2"
        op = max(0.05, min(1.0, opacity))

        mask_path = get_mask_path(shape)
        if mask_path:
            # 3-input chain: video, watermark, mask. alphamerge then opacity.
            filter_complex = (
                f"[1:v]scale={tw}:{th},format=rgba[wm0];"
                f"[2:v]scale={tw}:{th},format=gray[mask];"
                f"[wm0][mask]alphamerge[wm1];"
                f"[wm1]colorchannelmixer=aa={op:.2f}[wm];"
                f"[0:v][wm]overlay={pos}:format=auto:shortest=1[out]"
            )
            cmd = [
                'ffmpeg', '-y',
                '-i', input_path,
                '-i', watermark_path,
                '-i', mask_path,
                '-filter_complex', filter_complex,
                '-map', '[out]', '-map', '0:a?',
                '-c:a', 'copy',
            ]
        else:
            filter_complex = (
                f"[1:v]scale={tw}:{th},format=rgba,"
                f"colorchannelmixer=aa={op:.2f}[wm];"
                f"[0:v][wm]overlay={pos}:format=auto:shortest=1[out]"
            )
            cmd = [
                'ffmpeg', '-y',
                '-i', input_path,
                '-i', watermark_path,
                '-filter_complex', filter_complex,
                '-map', '[out]', '-map', '0:a?',
                '-c:a', 'copy',
            ]
        cmd.extend(self._get_encode_args())
        cmd.append(output_path)
        logger.info(f"Applying watermark: {watermark_path} pos=({cx:.2f},{cy:.2f}) size={tw}x{th} shape={shape} op={op:.2f}")
        if task:
            return self._run_ffmpeg_tracked(cmd, task, db, progress_start, progress_end,
                                            self.get_media_duration(input_path))
        process = subprocess.run(cmd, capture_output=True, timeout=7200)
        if process.returncode == 0:
            return {"success": True}
        error_msg = process.stderr.decode(errors='replace')[-500:]
        return {"success": False, "error": f"Watermark failed: {error_msg}"}

    def apply_text_watermark(
        self,
        input_path: str,
        output_path: str,
        text: str,
        font_path: str,
        font_name: str,
        font_size: int,
        color: str,
        angle: float,
        x: float,
        y: float,
        opacity: float,
        resolution: str,
        task=None,
        db=None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> Dict:
        """Render a text watermark (with optional rotation) at free position (center x,y in 0..1).

        - If angle == 0, draws text directly via drawtext at (W*x - tw/2, H*y - th/2).
        - If angle != 0, renders text on a transparent canvas, rotates it,
          and overlays at (main_w*x - overlay_w/2, main_h*y - overlay_h/2).
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        width_s, height_s = resolution.split('x')
        out_w = int(width_s)
        cx = max(0.0, min(1.0, x))
        cy = max(0.0, min(1.0, y))

        op = max(0.05, min(1.0, opacity))
        # Normalize hex color to ffmpeg-friendly form (e.g. #FFFFFF -> 0xFFFFFF)
        if color.startswith('#'):
            color_ff = '0x' + color[1:]
        else:
            color_ff = color
        fontcolor = f"{color_ff}@{op:.2f}"

        # Write text to a tempfile (avoids escaping headaches)
        text_file = os.path.join(os.path.dirname(output_path), "wm_text.txt")
        with open(text_file, "w", encoding="utf-8") as f:
            f.write(text)
        text_file_ff = text_file.replace('\\', '/').replace(':', r'\:')

        # Font argument: prefer fontfile, fallback to font name (fontconfig)
        if font_path and os.path.exists(font_path):
            font_path_ff = font_path.replace('\\', '/').replace(':', r'\:')
            font_arg = f"fontfile='{font_path_ff}'"
        else:
            font_arg = f"font='{font_name}'"

        if abs(angle) < 0.1:
            # No rotation: drawtext directly on main video at center (cx, cy)
            xy = f"x=W*{cx:.4f}-tw/2:y=H*{cy:.4f}-th/2"
            filter_complex = (
                f"[0:v]drawtext={font_arg}:textfile='{text_file_ff}':"
                f"fontsize={font_size}:fontcolor={fontcolor}:{xy}[out]"
            )
        else:
            # Rotation: render text on transparent canvas, rotate, overlay at center (cx, cy)
            est_w = max(int(len(text) * font_size * 0.7) + 40, 200)
            est_h = int(font_size * 1.6) + 40
            pos = f"main_w*{cx:.4f}-overlay_w/2:main_h*{cy:.4f}-overlay_h/2"
            rad = f"{angle}*PI/180"
            filter_complex = (
                f"color=c=0x00000000:s={est_w}x{est_h}:r=30[txtbg];"
                f"[txtbg]drawtext={font_arg}:textfile='{text_file_ff}':"
                f"fontsize={font_size}:fontcolor={fontcolor}:x=(w-tw)/2:y=(h-th)/2[txt];"
                f"[txt]rotate={rad}:c=0x00000000:ow=rotw({rad}):oh=roth({rad})[rtxt];"
                f"[0:v][rtxt]overlay={pos}:format=auto:shortest=1[out]"
            )

        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-filter_complex', filter_complex,
            '-map', '[out]', '-map', '0:a?',
            '-c:a', 'copy',
        ]
        cmd.extend(self._get_encode_args())
        cmd.append(output_path)

        logger.info(f"Applying text watermark: '{text[:40]}' pos=({cx:.2f},{cy:.2f}) size={font_size} angle={angle}")
        try:
            if task:
                return self._run_ffmpeg_tracked(cmd, task, db, progress_start, progress_end,
                                                self.get_media_duration(input_path))
            process = subprocess.run(cmd, capture_output=True, timeout=7200)
            if process.returncode == 0:
                return {"success": True}
            error_msg = process.stderr.decode(errors='replace')[-500:]
            return {"success": False, "error": f"Text watermark failed: {error_msg}"}
        finally:
            # Cleanup text file even if subprocess raises (timeout, etc.)
            try:
                if os.path.exists(text_file):
                    os.remove(text_file)
            except Exception:
                pass

    def apply_visualizer(
        self,
        input_path: str,
        output_path: str,
        audio_path: str,
        style: str,
        x: float,
        y: float,
        w: int,
        h: int,
        color1: str,
        color2: str,
        opacity: float,
        bg_mode: str,
        bg_color: str,
        bg_opacity: float,
        spectrum_preset: str,
        resolution: str,
        bars_mode: str = "bar",
        waveform_mode: str = "cline",
        waveform_mirror: bool = False,
        task=None,
        db=None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> Dict:
        """Render an audio visualizer and overlay it on the video at center
        (x, y) in 0..1, sized w x h px. Styles: bars, waveform, spectrum, cqt.

        Audio source for the viz comes from `audio_path` (already sped) — the
        video's own audio stream is preserved with `-c:a copy`.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cx = max(0.0, min(1.0, x))
        cy = max(0.0, min(1.0, y))
        # Even pixels — most viz filters require divisible-by-2 dims.
        vw = max(64, min(int(w), 4096)) // 2 * 2
        vh = max(32, min(int(h), 1080)) // 2 * 2
        op = max(0.05, min(1.0, opacity))

        def _hex_to_ff(hx: str) -> str:
            # FFmpeg color filters accept "0xRRGGBB" or named colors.
            return ("0x" + hx[1:]) if hx.startswith("#") else hx

        c1 = _hex_to_ff(color1)
        c2 = _hex_to_ff(color2)
        bg_c = _hex_to_ff(bg_color)
        bg_op = max(0.0, min(1.0, bg_opacity))

        style_l = (style or "bars").lower()
        bars_mode_l = (bars_mode or "bar").lower()
        if bars_mode_l not in {"bar", "line", "dot"}:
            bars_mode_l = "bar"
        waveform_mode_l = (waveform_mode or "cline").lower()
        if waveform_mode_l not in {"cline", "line", "point", "p2p"}:
            waveform_mode_l = "cline"

        # Build per-style chain ending in [viz0] sized exactly vw x vh.
        if style_l == "bars":
            # showfreqs (~64 bars across width). ascale=cbrt smooths motion.
            viz_chain = (
                f"[1:a]showfreqs=s={vw}x{vh}:mode={bars_mode_l}:ascale=cbrt:"
                f"fscale=log:win_size=2048:colors={c1}|{c2},format=rgba[viz0]"
            )
        elif style_l == "waveform":
            if waveform_mirror:
                # Render at half-height, vstack with vflipped copy for symmetric look.
                half_h = max(2, vh // 2)
                viz_chain = (
                    f"[1:a]showwaves=s={vw}x{half_h}:mode={waveform_mode_l}:"
                    f"rate=30:colors={c1},format=rgba,split[wtop][wbot];"
                    f"[wbot]vflip[wbotf];"
                    f"[wtop][wbotf]vstack=inputs=2,scale={vw}:{vh}[viz0]"
                )
            else:
                viz_chain = (
                    f"[1:a]showwaves=s={vw}x{vh}:mode={waveform_mode_l}:rate=30:"
                    f"colors={c1},format=rgba[viz0]"
                )
        elif style_l == "spectrum":
            preset = (spectrum_preset or "rainbow").lower()
            allowed = {
                "channel", "intensity", "rainbow", "moreland", "nebulae",
                "fire", "fiery", "fruit", "cool", "magma", "green", "viridis",
                "plasma", "cividis", "terrain",
            }
            if preset not in allowed:
                preset = "rainbow"
            viz_chain = (
                f"[1:a]showspectrum=s={vw}x{vh}:mode=combined:slide=scroll:"
                f"color={preset}:scale=log:saturation=1,format=rgba[viz0]"
            )
        elif style_l == "cqt":
            # showcqt is music-aware (constant-Q transform). axis_h=0 disables
            # the labelled note-axis ribbon at the bottom; bar_h fills the rest.
            viz_chain = (
                f"[1:a]showcqt=s={vw}x{vh}:axis_h=0:bar_h={vh}:fps=30:"
                f"basefreq=27.5:endfreq=20000:cscheme=1|0|0|0|1|0,"
                f"format=rgba[viz0]"
            )
        else:
            return {"success": False, "error": f"Unknown visualizer style: {style}"}

        # Apply opacity to viz layer.
        viz_chain += f";[viz0]colorchannelmixer=aa={op:.3f}[vizop]"

        # Optional solid background under viz.
        if bg_mode == "solid" and bg_op > 0:
            bg_filter = (
                f"color=c={bg_c}@{bg_op:.3f}:s={vw}x{vh}:r=30,format=rgba[bg];"
                f"[bg][vizop]overlay=0:0:format=auto[viz]"
            )
            viz_full = f"{viz_chain};{bg_filter}"
        else:
            viz_full = f"{viz_chain};[vizop]copy[viz]"

        pos = f"main_w*{cx:.4f}-overlay_w/2:main_h*{cy:.4f}-overlay_h/2"
        filter_complex = (
            f"{viz_full};"
            f"[0:v][viz]overlay={pos}:format=auto:shortest=1[out]"
        )

        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-i', audio_path,
            '-filter_complex', filter_complex,
            '-map', '[out]', '-map', '0:a?',
            '-c:a', 'copy',
        ]
        cmd.extend(self._get_encode_args())
        cmd.append(output_path)

        logger.info(
            f"Applying visualizer: style={style_l} pos=({cx:.2f},{cy:.2f}) "
            f"size={vw}x{vh} op={op:.2f} bg={bg_mode}"
        )
        if task:
            return self._run_ffmpeg_tracked(
                cmd, task, db, progress_start, progress_end,
                self.get_media_duration(input_path),
            )
        process = subprocess.run(cmd, capture_output=True, timeout=7200)
        if process.returncode == 0:
            return {"success": True}
        error_msg = process.stderr.decode(errors='replace')[-500:]
        return {"success": False, "error": f"Visualizer failed: {error_msg}"}

    def apply_stickers(
        self,
        input_path: str,
        output_path: str,
        stickers: List[Dict],
        resolution: str,
        task=None,
        db=None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> Dict:
        """Overlay one or more sticker images / animated GIFs / WebPs / APNGs.

        Each sticker has center-based normalized x,y, absolute size in px, an
        opacity in [0,1] and an optional [start_time, end_time] visibility
        window. Animated stickers loop for as long as they're visible
        (`-stream_loop -1`).
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Discard stickers with bad paths upfront so the ffmpeg cmd doesn't
        # reference non-existent inputs (which would fail the whole filter).
        valid: List[Dict] = []
        for st in stickers:
            p = st.get("image_path") or ""
            if p and os.path.exists(p):
                valid.append(st)
            else:
                logger.warning(f"Skipping sticker with invalid path: {p!r}")
        if not valid:
            return {"success": False, "error": "No valid stickers"}

        video_duration = self.get_media_duration(input_path)

        cmd = ['ffmpeg', '-y', '-i', input_path]
        # Each sticker becomes its own input so we can scale + position it
        # independently. -stream_loop -1 only matters for animated formats but
        # is harmless on static PNG/JPG.
        for st in valid:
            ext = os.path.splitext(st["image_path"])[1].lower()
            if ext in {".gif", ".webp", ".apng"}:
                cmd.extend(['-ignore_loop', '0', '-stream_loop', '-1'])
            cmd.extend(['-i', st["image_path"]])

        # Build filter graph: chain overlay nodes [v0]+[1]→[v1], [v1]+[2]→[v2]…
        chain_parts = []
        prev_label = "0:v"
        for i, st in enumerate(valid, start=1):
            x = max(0.0, min(1.0, float(st.get("x", 0.5))))
            y = max(0.0, min(1.0, float(st.get("y", 0.5))))
            w = max(8, min(int(st.get("w", 200)), 4096)) // 2 * 2
            h = max(8, min(int(st.get("h", 200)), 4096)) // 2 * 2
            op = max(0.0, min(1.0, float(st.get("opacity", 1.0))))
            start = max(0.0, float(st.get("start_time", 0.0)))
            end_raw = st.get("end_time")
            end = float(end_raw) if end_raw is not None else (video_duration or 1e9)
            # Avoid zero/negative windows after clamping.
            if end <= start:
                end = start + 0.1

            # Scale + apply per-sticker opacity via colorchannelmixer alpha.
            # format=rgba ensures alpha exists (PNG keeps it; JPG gains it).
            chain_parts.append(
                f"[{i}:v]scale={w}:{h},format=rgba,"
                f"colorchannelmixer=aa={op:.3f}[s{i}]"
            )
            pos = f"main_w*{x:.4f}-overlay_w/2:main_h*{y:.4f}-overlay_h/2"
            out_label = f"v{i}" if i < len(valid) else "out"
            chain_parts.append(
                f"[{prev_label}][s{i}]overlay="
                f"x={pos.split(':')[0]}:y={pos.split(':')[1]}"
                f":enable='between(t,{start:.3f},{end:.3f})'"
                f":format=auto[{out_label}]"
            )
            prev_label = out_label

        filter_complex = ";".join(chain_parts)
        cmd.extend([
            '-filter_complex', filter_complex,
            '-map', '[out]', '-map', '0:a?',
            '-c:a', 'copy',
        ])
        cmd.extend(self._get_encode_args())
        cmd.append(output_path)

        logger.info(f"Applying {len(valid)} sticker(s)")
        if task:
            return self._run_ffmpeg_tracked(
                cmd, task, db, progress_start, progress_end,
                self.get_media_duration(input_path),
            )
        process = subprocess.run(cmd, capture_output=True, timeout=7200)
        if process.returncode == 0:
            return {"success": True}
        error_msg = process.stderr.decode(errors='replace')[-500:]
        return {"success": False, "error": f"Stickers failed: {error_msg}"}

    def apply_subtitle(
        self,
        input_path: str,
        output_path: str,
        srt_path: str,
        style: Dict,
        animation: str,
        resolution: str,
        task=None,
        db=None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> Dict:
        """Burn an SRT (converted on the fly to ASS for styling+animation) into the video.

        Returns the standard {"success": bool, ...} plus a "warning" key when
        SRT timing extends past video duration (we truncate, caller surfaces it).
        """
        from app.services import subtitle_renderer

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        if not os.path.exists(srt_path):
            return {"success": False, "error": f"SRT not found: {srt_path}"}

        width_s, height_s = resolution.split('x')
        play_w, play_h = int(width_s), int(height_s)

        video_duration = self.get_media_duration(input_path)
        if video_duration <= 0:
            return {"success": False, "error": "Could not determine video duration for subtitle"}

        ass_path = os.path.join(os.path.dirname(output_path), "subtitle.ass")
        try:
            try:
                meta = subtitle_renderer.srt_to_ass(
                    srt_path=srt_path,
                    output_ass_path=ass_path,
                    style=subtitle_renderer.SubtitleStyle(**style),
                    animation=animation,
                    play_res_x=play_w,
                    play_res_y=play_h,
                    max_duration=video_duration,
                )
            except Exception as e:
                return {"success": False, "error": f"SRT→ASS failed: {e}"}

            warning = None
            if meta["truncated_count"] > 0:
                warning = (
                    f"SRT extends past video ({meta['last_end']:.1f}s > "
                    f"{video_duration:.1f}s); truncated {meta['truncated_count']} line(s)."
                )
                logger.warning(warning)

            # ffmpeg subtitles filter needs colon-escaped paths on Windows.
            ass_ff = ass_path.replace('\\', '/').replace(':', r'\:')
            from app.services.fonts import FONTS_DIR
            fonts_dir_ff = str(FONTS_DIR).replace('\\', '/').replace(':', r'\:')
            vf = f"subtitles='{ass_ff}':fontsdir='{fonts_dir_ff}'"

            cmd = [
                'ffmpeg', '-y',
                '-i', input_path,
                '-vf', vf,
                '-map', '0:v', '-map', '0:a?',
                '-c:a', 'copy',
            ]
            cmd.extend(self._get_encode_args())
            cmd.append(output_path)

            logger.info(
                f"Burning subtitle: {os.path.basename(srt_path)} "
                f"({meta['kept_segments']}/{meta['total_segments']} segs, anim={animation})"
            )
            try:
                if task:
                    res = self._run_ffmpeg_tracked(
                        cmd, task, db, progress_start, progress_end, video_duration
                    )
                else:
                    process = subprocess.run(cmd, capture_output=True, timeout=7200)
                    if process.returncode == 0:
                        res = {"success": True}
                    else:
                        error_msg = process.stderr.decode(errors='replace')[-500:]
                        res = {"success": False, "error": f"Subtitle burn failed: {error_msg}"}
            except Exception as e:
                res = {"success": False, "error": f"Subtitle burn crashed: {e}"}

            if warning and res.get("success"):
                res["warning"] = warning
            return res
        finally:
            try:
                if os.path.exists(ass_path):
                    os.remove(ass_path)
            except Exception:
                pass

    def apply_fade(
        self,
        input_path: str,
        output_path: str,
        fade_in: float,
        fade_out: float,
        task=None,
        db=None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> Dict:
        """Apply fade-in and/or fade-out to both video and audio."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        duration = self.get_media_duration(input_path)
        if duration <= 0:
            return {"success": False, "error": "Could not determine duration for fade"}

        v_parts: List[str] = []
        a_parts: List[str] = []
        if fade_in > 0:
            v_parts.append(f"fade=t=in:st=0:d={fade_in:.2f}")
            a_parts.append(f"afade=t=in:st=0:d={fade_in:.2f}")
        if fade_out > 0:
            st = max(0.0, duration - fade_out)
            v_parts.append(f"fade=t=out:st={st:.2f}:d={fade_out:.2f}")
            a_parts.append(f"afade=t=out:st={st:.2f}:d={fade_out:.2f}")

        if not v_parts and not a_parts:
            return {"success": False, "error": "No fade parameters"}

        cmd = ['ffmpeg', '-y', '-i', input_path]
        if v_parts:
            cmd.extend(['-vf', ",".join(v_parts)])
        if a_parts:
            cmd.extend(['-af', ",".join(a_parts)])
            cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
        else:
            cmd.extend(['-c:a', 'copy'])
        cmd.extend(self._get_encode_args())
        cmd.append(output_path)
        logger.info(f"Applying fade in={fade_in:.2f}s out={fade_out:.2f}s (dur={duration:.2f}s)")
        if task:
            return self._run_ffmpeg_tracked(cmd, task, db, progress_start, progress_end, duration)
        process = subprocess.run(cmd, capture_output=True, timeout=7200)
        if process.returncode == 0:
            return {"success": True}
        error_msg = process.stderr.decode(errors='replace')[-500:]
        return {"success": False, "error": f"Fade failed: {error_msg}"}

    def _build_ad_color_zoom_filter(
        self,
        width: str, height: str,
        zoom: bool, zoom_factor: float,
        color: bool,
        saturation: float, contrast: float, gamma: float, hue_shift: float,
    ) -> str:
        """Build the partial ffmpeg filter chain for zoom+crop and/or color grading.
        Returns a leading-comma string suitable for appending to a per-clip chain
        (e.g. ',scale=...,crop=...,eq=...,hue=...'), or '' when both groups are off."""
        parts: List[str] = []
        if zoom and zoom_factor > 1.0:
            zf = max(1.0, min(AD_MAX_ZOOM, float(zoom_factor)))
            zw = int(int(width) * zf) // 2 * 2
            zh = int(int(height) * zf) // 2 * 2
            parts.append(f"scale={zw}:{zh},crop={width}:{height}")
        if color:
            eq_parts = []
            if abs(saturation - 1.0) > AD_RATE_EPSILON:
                eq_parts.append(f"saturation={max(0.0, saturation):.3f}")
            if abs(contrast - 1.0) > AD_RATE_EPSILON:
                eq_parts.append(f"contrast={contrast:.3f}")
            if abs(gamma - 1.0) > AD_RATE_EPSILON:
                eq_parts.append(f"gamma={max(0.1, gamma):.3f}")
            if eq_parts:
                parts.append(f"eq={':'.join(eq_parts)}")
            if abs(hue_shift) > 0.1:
                parts.append(f"hue=h={hue_shift:.2f}")
        return ("," + ",".join(parts)) if parts else ""

    def strip_metadata(self, input_path: str, output_path: str) -> Dict:
        """Strip user-set container metadata (title/comment/etc) via stream copy.
        Note: the mp4 muxer always writes its own `encoder=Lavf<version>` udta
        tag which `-map_metadata -1` cannot reach — that tag is harmless from
        an anti-detection standpoint (every legit ffmpeg output has it)."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-map_metadata', '-1',
            '-metadata', 'title=', '-metadata', 'comment=',
            '-c', 'copy', output_path,
        ]
        logger.info("Stripping metadata")
        process = subprocess.run(cmd, capture_output=True, timeout=600)
        if process.returncode == 0:
            return {"success": True}
        error_msg = process.stderr.decode(errors='replace')[-500:]
        return {"success": False, "error": f"Strip metadata failed: {error_msg}"}

    def _run_merge_pipeline(
        self,
        video_paths: List[str],
        audio_path: str,
        output_dir: str,
        story_folder: str,
        audio_speed: float,
        resolution: str,
        task: Optional[models.Task],
        db: Session,
        banner_image: Optional[str] = None,
        banner_video_scale: float = 1.0,
        banner_video_offset_x: float = 0.0,
        banner_video_offset_y: float = 0.0,
        banner_video_scale_x: Optional[float] = None,
        banner_video_scale_y: Optional[float] = None,
        overlay_opacity: float = 0.0,
        watermark_image: Optional[str] = None,
        watermark_x: float = 0.92,
        watermark_y: float = 0.92,
        watermark_w: int = 200,
        watermark_h: int = 200,
        watermark_shape: str = "none",
        watermark_opacity: float = 0.85,
        watermark_text: Optional[str] = None,
        watermark_text_font: str = "DejaVu Sans (system default)",
        watermark_text_size: int = 48,
        watermark_text_color: str = "#FFFFFF",
        watermark_text_angle: float = 0.0,
        watermark_text_x: float = 0.92,
        watermark_text_y: float = 0.92,
        watermark_text_opacity: float = 0.85,
        subtitle_srt_path: Optional[str] = None,
        subtitle_animation: str = "fade",
        subtitle_font: str = "Be Vietnam Pro (Vietnamese)",
        subtitle_font_size: int = 56,
        subtitle_color: str = "#FFFFFF",
        subtitle_outline_color: str = "#000000",
        subtitle_outline_width: int = 3,
        subtitle_shadow: int = 0,
        subtitle_bold: bool = True,
        subtitle_italic: bool = False,
        subtitle_align: str = "center",
        subtitle_x: float = 0.5,
        subtitle_y: float = 0.85,
        subtitle_opacity: float = 1.0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        mute_source_videos: bool = True,
        transitions_pool: Optional[List[str]] = None,
        transition_duration: float = 0.5,
        ad_flip_random: bool = False,
        ad_flip_all: bool = False,
        ad_zoom: bool = False,
        ad_zoom_factor: float = 1.08,
        ad_color: bool = False,
        ad_saturation: float = 1.05,
        ad_contrast: float = 1.00,
        ad_gamma: float = 1.00,
        ad_hue_shift: float = 0.0,
        ad_clip_speed_jitter: bool = False,
        ad_clip_speed_jitter_range: float = 0.03,
        ad_strip_metadata: bool = False,
        visualizer_enabled: bool = False,
        visualizer_style: str = "bars",
        visualizer_x: float = 0.5,
        visualizer_y: float = 0.85,
        visualizer_w: int = 800,
        visualizer_h: int = 120,
        visualizer_color1: str = "#00E5FF",
        visualizer_color2: str = "#FF00FF",
        visualizer_opacity: float = 0.85,
        visualizer_bg_mode: str = "transparent",
        visualizer_bg_color: str = "#000000",
        visualizer_bg_opacity: float = 0.3,
        visualizer_spectrum_preset: str = "rainbow",
        visualizer_bars_mode: str = "bar",
        visualizer_waveform_mode: str = "cline",
        visualizer_waveform_mirror: bool = False,
        stickers: Optional[List[Dict]] = None,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.12,
        bgm_loop: bool = True,
        bgm_ducking: bool = True,
        bgm_fade: float = 2.0,
    ) -> Dict:
        """
        Run the merge pipeline (speed audio -> concat bounded -> merge).
        Separated so it can be retried.
        """
        flip_mode = "all" if ad_flip_all else ("random" if ad_flip_random else "none")
        jitter = ad_clip_speed_jitter_range if ad_clip_speed_jitter else 0.0
        concat_path = os.path.join(output_dir, "bg_video_concat.mp4")
        sped_audio_path = os.path.join(output_dir, "audio_sped.mp3")
        final_output = os.path.join(output_dir, f"{story_folder}_final.mp4")

        # 1. Speed up audio first so we know the exact target duration before
        # concatenating — that way ffmpeg can stop encoding the video at exactly
        # `sped_audio_duration` instead of re-encoding the trailing excess of
        # the last clip just to discard it later.
        logger.info(f"Speeding up audio to {audio_speed}x...")
        speed_result = self.speed_up_audio(audio_path, sped_audio_path, audio_speed)
        if not speed_result["success"]:
            raise RuntimeError(f"Audio speed up failed: {speed_result.get('error')}")

        # 1b. Mix background music under the narration (no-op when no BGM set).
        # Done before measuring the target duration so BGM never lengthens the
        # video — the mixed track is clamped to the narration's length.
        sped_audio_path, bgm_warning = self._maybe_mix_bgm(
            sped_audio_path, output_dir,
            bgm_path, bgm_volume, bgm_loop, bgm_ducking, bgm_fade,
        )

        sped_audio_duration = self.get_media_duration(sped_audio_path)
        logger.info(f"Sped audio duration: {self._format_duration(sped_audio_duration)}")

        if task:
            task.progress = 30
            db.commit()

        # 2. Concat videos, bounded to sped_audio_duration so the encoder stops
        # at the right moment and the last clip is cut mid-frame as needed.
        # When banner is used, concat at source aspect ratio (no black padding)
        concat_resolution = resolution
        if banner_image and os.path.exists(banner_image):
            src_w, src_h = self.get_video_dimensions(video_paths[0])
            if src_w > 0 and src_h > 0:
                out_w, out_h = [int(x) for x in resolution.split('x')]
                # Scale source aspect ratio to fit within output resolution
                scale = min(out_w / src_w, out_h / src_h)
                concat_w = int(src_w * scale) // 2 * 2  # ensure even
                concat_h = int(src_h * scale) // 2 * 2
                concat_resolution = f"{concat_w}x{concat_h}"
                logger.info(f"Banner mode: concat at {concat_resolution} (source {src_w}x{src_h})")

        logger.info(f"Concatenating {len(video_paths)} videos (bounded to {sped_audio_duration:.2f}s)...")

        ad_color_zoom_filter = self._build_ad_color_zoom_filter(
            *concat_resolution.split('x'),
            zoom=ad_zoom, zoom_factor=ad_zoom_factor,
            color=ad_color,
            saturation=ad_saturation, contrast=ad_contrast,
            gamma=ad_gamma, hue_shift=ad_hue_shift,
        )
        concat_result = self.concatenate_videos_from_folder(
            video_paths, concat_path, concat_resolution,
            keep_audio=not mute_source_videos,
            transitions_pool=transitions_pool,
            transition_duration=transition_duration,
            flip_mode=flip_mode,
            clip_speed_jitter=jitter,
            ad_color_zoom_filter=ad_color_zoom_filter,
            max_duration=sped_audio_duration,
        )
        if not concat_result["success"]:
            raise RuntimeError(f"Video concatenation failed: {concat_result.get('error')}")

        if task:
            task.progress = 75
            db.commit()

        # 3.5. Overlay on banner if provided
        video_for_merge = concat_path
        composite_path = None
        if banner_image and os.path.exists(banner_image):
            composite_path = os.path.join(output_dir, "bg_video_composite.mp4")
            logger.info(f"Overlaying video on banner: {banner_image}")
            overlay_result = self.overlay_on_banner(
                concat_path, banner_image, composite_path,
                resolution, sped_audio_duration, banner_video_scale,
                banner_video_offset_x, banner_video_offset_y,
                scale_x=banner_video_scale_x, scale_y=banner_video_scale_y
            )
            if not overlay_result["success"]:
                raise RuntimeError(f"Banner overlay failed: {overlay_result.get('error')}")
            video_for_merge = composite_path

            if task:
                task.progress = 82
                db.commit()

        # 4. Plan post-process steps (after audio+video merge)
        # visualizer is placed before watermark/subtitle so they sit on top of
        # the rendered viz layer (logo and captions stay readable).
        post_steps: List[str] = []
        if overlay_opacity > 0:
            post_steps.append("overlay")
        if visualizer_enabled:
            post_steps.append("visualizer")
        if watermark_image and os.path.exists(watermark_image):
            post_steps.append("watermark")
        # Stickers go on top of background but under subtitles, so captions
        # stay readable even when a sticker happens to land near the same y.
        if stickers and any(s.get("image_path") and os.path.exists(s["image_path"]) for s in stickers):
            post_steps.append("stickers")
        if subtitle_srt_path and os.path.exists(subtitle_srt_path):
            post_steps.append("subtitle")
        if watermark_text and watermark_text.strip():
            post_steps.append("text_watermark")
        if fade_in > 0 or fade_out > 0:
            post_steps.append("fade")
        if ad_strip_metadata:
            post_steps.append("ad_strip_metadata")

        # If no post-process needed, merge directly to final
        merged_target = final_output if not post_steps else os.path.join(output_dir, "bg_video_merged.mp4")

        logger.info(f"Merging audio and video... (video={video_for_merge}, audio={sped_audio_path})")
        merge_result = self.merge_audio_video(video_for_merge, sped_audio_path, merged_target)
        if not merge_result["success"]:
            raise RuntimeError(f"Audio-video merge failed: {merge_result.get('error')}")
        logger.info(f"Audio-video merge done -> {merged_target}")

        if task:
            task.progress = 90
            db.commit()

        # 5. Apply post-process steps in sequence
        # Progress 90 -> 99 distributed across steps, 100 reserved for DB save
        n_post = len(post_steps)
        intermediates: List[str] = [merged_target] if post_steps else []
        current = merged_target
        for i, step in enumerate(post_steps):
            is_last = i == n_post - 1
            next_path = final_output if is_last else os.path.join(output_dir, f"bg_post_{step}.mp4")

            step_start = 90 + round(i * 9 / n_post)
            step_end = 90 + round((i + 1) * 9 / n_post)
            logger.info(f"Post-process [{i+1}/{n_post}] {step} ({step_start}%→{step_end}%) -> {os.path.basename(next_path)}")

            _t0 = time.monotonic()

            if step == "overlay":
                step_result = self.apply_overlay(current, next_path, overlay_opacity, resolution,
                                                 task, db, step_start, step_end)
            elif step == "visualizer":
                step_result = self.apply_visualizer(
                    current, next_path, sped_audio_path,
                    visualizer_style, visualizer_x, visualizer_y,
                    visualizer_w, visualizer_h,
                    visualizer_color1, visualizer_color2, visualizer_opacity,
                    visualizer_bg_mode, visualizer_bg_color, visualizer_bg_opacity,
                    visualizer_spectrum_preset, resolution,
                    bars_mode=visualizer_bars_mode,
                    waveform_mode=visualizer_waveform_mode,
                    waveform_mirror=visualizer_waveform_mirror,
                    task=task, db=db, progress_start=step_start, progress_end=step_end,
                )
            elif step == "watermark":
                step_result = self.apply_watermark(
                    current, next_path, watermark_image,
                    watermark_x, watermark_y,
                    watermark_w, watermark_h, watermark_shape,
                    watermark_opacity, resolution,
                    task, db, step_start, step_end,
                )
            elif step == "stickers":
                step_result = self.apply_stickers(
                    current, next_path, stickers or [], resolution,
                    task, db, step_start, step_end,
                )
            elif step == "text_watermark":
                from app.services.fonts import ensure_font
                font_name, font_path = ensure_font(watermark_text_font)
                step_result = self.apply_text_watermark(
                    current, next_path, watermark_text, font_path, font_name,
                    watermark_text_size, watermark_text_color, watermark_text_angle,
                    watermark_text_x, watermark_text_y,
                    watermark_text_opacity, resolution,
                    task, db, step_start, step_end,
                )
            elif step == "subtitle":
                from app.services.fonts import ensure_font
                sub_font_name, _ = ensure_font(subtitle_font)
                step_result = self.apply_subtitle(
                    current, next_path, subtitle_srt_path,
                    {
                        "font_name": sub_font_name,
                        "font_size": subtitle_font_size,
                        "color": subtitle_color,
                        "outline_color": subtitle_outline_color,
                        "outline_width": subtitle_outline_width,
                        "shadow": subtitle_shadow,
                        "bold": subtitle_bold,
                        "italic": subtitle_italic,
                        "align": subtitle_align,
                        "x": subtitle_x,
                        "y": subtitle_y,
                        "opacity": subtitle_opacity,
                    },
                    subtitle_animation, resolution,
                    task, db, step_start, step_end,
                )
            elif step == "fade":
                step_result = self.apply_fade(current, next_path, fade_in, fade_out,
                                              task, db, step_start, step_end)
            elif step == "ad_strip_metadata":
                step_result = self.strip_metadata(current, next_path)
            else:
                logger.warning(f"Unknown post-process step '{step}', skipping")
                continue

            elapsed = time.monotonic() - _t0
            if not step_result["success"]:
                logger.error(f"Post-process '{step}' FAILED after {elapsed:.1f}s: {step_result.get('error')}")
                raise RuntimeError(f"{step} failed: {step_result.get('error')}")

            logger.info(f"Post-process '{step}' done in {elapsed:.1f}s")
            if task:
                task.progress = step_end
                db.commit()

            if not is_last:
                intermediates.append(next_path)
            current = next_path

        # Get final file info
        final_duration = self.get_media_duration(final_output)
        final_size = os.path.getsize(final_output) if os.path.exists(final_output) else 0

        # Cleanup intermediate files. sped_audio_path may point at the BGM-mixed
        # file; add the pre-mix audio_sped.mp3 explicitly so it isn't left behind.
        cleanup_files = [concat_path, sped_audio_path, os.path.join(output_dir, "audio_sped.mp3")]
        if composite_path:
            cleanup_files.append(composite_path)
        cleanup_files.extend(intermediates)
        for tmp in cleanup_files:
            try:
                if os.path.exists(tmp) and tmp != final_output:
                    os.remove(tmp)
            except Exception:
                pass

        return {
            "success": True,
            "output_path": final_output,
            "duration": final_duration,
            "file_size": final_size,
            "bgm_warning": bgm_warning,
        }

    def process_story_video(
        self,
        story_id: str,
        task_id: str,
        db: Session,
        video_source_folder: str,
        audio_path: Optional[str] = None,
        clip_order: str = "shuffle",
        audio_speed: float = 1.07,
        transition_effect: str = "crossfade",
        transitions_pool: Optional[List[str]] = None,
        transition_duration: float = 0.5,
        resolution: str = "1920x1080",
        banner_image: Optional[str] = None,
        banner_video_scale: float = 1.0,
        banner_video_offset_x: float = 0.0,
        banner_video_offset_y: float = 0.0,
        banner_video_scale_x: Optional[float] = None,
        banner_video_scale_y: Optional[float] = None,
        overlay_opacity: float = 0.0,
        watermark_image: Optional[str] = None,
        watermark_x: float = 0.92,
        watermark_y: float = 0.92,
        watermark_w: int = 200,
        watermark_h: int = 200,
        watermark_shape: str = "none",
        watermark_opacity: float = 0.85,
        watermark_text: Optional[str] = None,
        watermark_text_font: str = "DejaVu Sans (system default)",
        watermark_text_size: int = 48,
        watermark_text_color: str = "#FFFFFF",
        watermark_text_angle: float = 0.0,
        watermark_text_x: float = 0.92,
        watermark_text_y: float = 0.92,
        watermark_text_opacity: float = 0.85,
        subtitle_srt_path: Optional[str] = None,
        subtitle_animation: str = "fade",
        subtitle_font: str = "Be Vietnam Pro (Vietnamese)",
        subtitle_font_size: int = 56,
        subtitle_color: str = "#FFFFFF",
        subtitle_outline_color: str = "#000000",
        subtitle_outline_width: int = 3,
        subtitle_shadow: int = 0,
        subtitle_bold: bool = True,
        subtitle_italic: bool = False,
        subtitle_align: str = "center",
        subtitle_x: float = 0.5,
        subtitle_y: float = 0.85,
        subtitle_opacity: float = 1.0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        mute_source_videos: bool = True,
        ad_flip_random: bool = False,
        ad_flip_all: bool = False,
        ad_zoom: bool = False,
        ad_zoom_factor: float = 1.08,
        ad_color: bool = False,
        ad_saturation: float = 1.05,
        ad_contrast: float = 1.00,
        ad_gamma: float = 1.00,
        ad_hue_shift: float = 0.0,
        ad_clip_speed_jitter: bool = False,
        ad_clip_speed_jitter_range: float = 0.03,
        ad_strip_metadata: bool = False,
        visualizer_enabled: bool = False,
        visualizer_style: str = "bars",
        visualizer_x: float = 0.5,
        visualizer_y: float = 0.85,
        visualizer_w: int = 800,
        visualizer_h: int = 120,
        visualizer_color1: str = "#00E5FF",
        visualizer_color2: str = "#FF00FF",
        visualizer_opacity: float = 0.85,
        visualizer_bg_mode: str = "transparent",
        visualizer_bg_color: str = "#000000",
        visualizer_bg_opacity: float = 0.3,
        visualizer_spectrum_preset: str = "rainbow",
        visualizer_bars_mode: str = "bar",
        visualizer_waveform_mode: str = "cline",
        visualizer_waveform_mirror: bool = False,
        stickers: Optional[List[Dict]] = None,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.12,
        bgm_loop: bool = True,
        bgm_ducking: bool = True,
        bgm_fade: float = 2.0,
    ) -> Dict:
        """
        Full pipeline with temp folder + retry:
        1. Get MergedAudio from DB
        2. Calculate target_duration = audio_duration / speed
        3. Create a fresh temp folder (no reuse), select + copy clips into it
        4. Concat all clips from temp folder (concat demuxer)
        5. Speed up audio
        6. Merge audio + video
        7. Retry up to 2 times on failure
        8. Save VideoOutput to DB
        """
        task = None
        temp_folder = None
        try:
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                task.status = "running"
                task.progress = 0
                db.commit()

            # 1. Get audio source (custom path or from DB)
            if audio_path and os.path.exists(audio_path):
                logger.info(f"Using custom audio path: {audio_path}")
            else:
                merged_audio = db.query(models.MergedAudio).filter(
                    models.MergedAudio.story_id == story_id
                ).order_by(models.MergedAudio.created_at.desc()).first()

                if not merged_audio:
                    raise ValueError("No merged audio found for this story. Please complete audio merge first or provide a custom audio path.")

                audio_path = merged_audio.file_path
                logger.info(f"Using merged audio from DB: {audio_path}")

            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            audio_duration = self.get_media_duration(audio_path)
            if audio_duration <= 0:
                raise ValueError("Could not determine audio duration")

            logger.info(f"Audio duration: {self._format_duration(audio_duration)}")

            if task:
                task.progress = 5
                db.commit()

            # 2. Calculate target video duration (round up to next full minute)
            exact_duration = audio_duration / audio_speed
            target_duration = math.ceil(exact_duration / 60) * 60
            logger.info(f"Target video duration: {self._format_duration(exact_duration)} -> round up to {self._format_duration(target_duration)}")

            # Setup output paths
            story = db.query(models.Story).filter(models.Story.id == story_id).first()
            story_folder = story.title.replace(' ', '_') if story else story_id
            output_dir = os.path.join(settings.STORAGE_PATH, "videos", story_folder)
            os.makedirs(output_dir, exist_ok=True)

            # 3. Always re-scan source folder and create a fresh temp folder
            temp_folder = self._create_temp_folder(
                output_dir, video_source_folder, target_duration, clip_order
            )

            video_paths = self.get_temp_folder_videos(temp_folder)
            if not video_paths:
                raise ValueError(f"No video files found in temp folder: {temp_folder}")

            logger.info(f"Using temp folder: {temp_folder} ({len(video_paths)} clips)")

            if task:
                task.progress = 20
                db.commit()

            # 4-6. Run merge pipeline with retry (max 2 retries)
            max_retries = 2
            last_error = None

            for attempt in range(1, max_retries + 2):  # 1 attempt + 2 retries = 3 total
                try:
                    logger.info(f"Merge attempt {attempt}/{max_retries + 1}")
                    result = self._run_merge_pipeline(
                        video_paths, audio_path, output_dir, story_folder,
                        audio_speed, resolution, task, db, banner_image, banner_video_scale,
                        banner_video_offset_x, banner_video_offset_y,
                        banner_video_scale_x, banner_video_scale_y,
                        overlay_opacity,
                        watermark_image, watermark_x, watermark_y,
                        watermark_w, watermark_h, watermark_shape, watermark_opacity,
                        watermark_text, watermark_text_font, watermark_text_size,
                        watermark_text_color, watermark_text_angle,
                        watermark_text_x, watermark_text_y, watermark_text_opacity,
                        subtitle_srt_path, subtitle_animation, subtitle_font,
                        subtitle_font_size, subtitle_color,
                        subtitle_outline_color, subtitle_outline_width, subtitle_shadow,
                        subtitle_bold, subtitle_italic, subtitle_align,
                        subtitle_x, subtitle_y, subtitle_opacity,
                        fade_in, fade_out,
                        mute_source_videos=mute_source_videos,
                        transitions_pool=transitions_pool,
                        transition_duration=transition_duration,
                        ad_flip_random=ad_flip_random,
                        ad_flip_all=ad_flip_all,
                        ad_zoom=ad_zoom,
                        ad_zoom_factor=ad_zoom_factor,
                        ad_color=ad_color,
                        ad_saturation=ad_saturation,
                        ad_contrast=ad_contrast,
                        ad_gamma=ad_gamma,
                        ad_hue_shift=ad_hue_shift,
                        ad_clip_speed_jitter=ad_clip_speed_jitter,
                        ad_clip_speed_jitter_range=ad_clip_speed_jitter_range,
                        ad_strip_metadata=ad_strip_metadata,
                        visualizer_enabled=visualizer_enabled,
                        visualizer_style=visualizer_style,
                        visualizer_x=visualizer_x,
                        visualizer_y=visualizer_y,
                        visualizer_w=visualizer_w,
                        visualizer_h=visualizer_h,
                        visualizer_color1=visualizer_color1,
                        visualizer_color2=visualizer_color2,
                        visualizer_opacity=visualizer_opacity,
                        visualizer_bg_mode=visualizer_bg_mode,
                        visualizer_bg_color=visualizer_bg_color,
                        visualizer_bg_opacity=visualizer_bg_opacity,
                        visualizer_spectrum_preset=visualizer_spectrum_preset,
                        visualizer_bars_mode=visualizer_bars_mode,
                        visualizer_waveform_mode=visualizer_waveform_mode,
                        visualizer_waveform_mirror=visualizer_waveform_mirror,
                        stickers=stickers,
                        bgm_path=bgm_path,
                        bgm_volume=bgm_volume,
                        bgm_loop=bgm_loop,
                        bgm_ducking=bgm_ducking,
                        bgm_fade=bgm_fade,
                    )

                    if result["success"]:
                        # Deliver the finished long video to the user's output
                        # folder (Downloads by default). Serving/preview is
                        # path-based, so the DB just stores the delivered path.
                        _sub = safe_file_stem(story.title if story and story.title else story_id, story_id)
                        result["output_path"] = deliver_final(
                            result["output_path"], db,
                            filename=f"{story_folder}_final.mp4",
                            subfolder=_sub,
                        )

                        # 7. Save to DB
                        video_output = models.VideoOutput(
                            story_id=story_id,
                            audio_source_path=audio_path,
                            video_source_folder=video_source_folder,
                            output_path=result["output_path"],
                            file_size=result["file_size"],
                            duration=result["duration"],
                            audio_speed=audio_speed,
                            transition_effect=transition_effect,
                            transition_duration=transition_duration,
                            resolution=resolution,
                            status="completed"
                        )
                        db.add(video_output)

                        if task:
                            task.status = "completed"
                            task.progress = 100
                            # Non-fatal: BGM was configured but couldn't be mixed in,
                            # so the delivered video has no background music. Surface
                            # it instead of leaving the user to notice by listening.
                            if result.get("bgm_warning"):
                                task.error_message = result["bgm_warning"]
                        db.commit()

                        logger.info(f"Video processing completed: {result['output_path']}")
                        return result

                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Attempt {attempt} failed: {e}")
                    if attempt <= max_retries:
                        logger.info(f"Retrying... ({attempt}/{max_retries})")
                        if task:
                            task.progress = 20  # Reset progress for retry
                            task.error_message = f"Retry {attempt}: {e}"
                            db.commit()
                    else:
                        raise RuntimeError(f"Failed after {max_retries + 1} attempts. Last error: {last_error}")

        except Exception as e:
            logger.error(f"Video processing failed: {e}")
            db.rollback()
            try:
                if task:
                    task.status = "failed"
                    task.error_message = str(e)
                    db.commit()
            except Exception:
                db.rollback()

            # Save failed VideoOutput record
            try:
                video_output = models.VideoOutput(
                    story_id=story_id,
                    video_source_folder=video_source_folder,
                    audio_speed=audio_speed,
                    transition_effect=transition_effect,
                    transition_duration=transition_duration,
                    resolution=resolution,
                    status="failed",
                    error_message=str(e)
                )
                db.add(video_output)
                db.commit()
            except Exception:
                db.rollback()

            return {"success": False, "error": str(e)}

        finally:
            # Clean up this job's own temp folder (source clips already concatted
            # into the output). Only this render's folder is touched, so a
            # concurrent render for the same story is never affected.
            if temp_folder and os.path.isdir(temp_folder):
                logger.info(f"Removing temp folder: {temp_folder}")
                shutil.rmtree(temp_folder, ignore_errors=True)

    def trim_audio(self, input_path: str, output_path: str, duration: float) -> Dict:
        # Re-encode to mp3 rather than -c copy because the input may be flac/wav
        # and downstream merge expects a consistent codec.
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-t', str(duration),
            '-c:a', 'libmp3lame', '-b:a', '192k',
            '-vn',
            output_path,
        ]
        logger.info(f"Trimming audio to {duration:.2f}s")
        process = subprocess.run(cmd, capture_output=True, timeout=600)
        if process.returncode == 0:
            return {"success": True}
        error_msg = process.stderr.decode(errors='replace')[-500:]
        return {"success": False, "error": f"Audio trim failed: {error_msg}"}

    def render_preview(
        self,
        video_source_folder: str,
        audio_path: str,
        output_path: str,
        max_duration: float = 60.0,
        audio_speed: float = 1.07,
        resolution: str = "1920x1080",
        banner_image: Optional[str] = None,
        banner_video_scale: float = 1.0,
        banner_video_offset_x: float = 0.0,
        banner_video_offset_y: float = 0.0,
        banner_video_scale_x: Optional[float] = None,
        banner_video_scale_y: Optional[float] = None,
        overlay_opacity: float = 0.0,
        watermark_image: Optional[str] = None,
        watermark_x: float = 0.92,
        watermark_y: float = 0.92,
        watermark_w: int = 200,
        watermark_h: int = 200,
        watermark_shape: str = "none",
        watermark_opacity: float = 0.85,
        watermark_text: Optional[str] = None,
        watermark_text_font: str = "DejaVu Sans (system default)",
        watermark_text_size: int = 48,
        watermark_text_color: str = "#FFFFFF",
        watermark_text_angle: float = 0.0,
        watermark_text_x: float = 0.92,
        watermark_text_y: float = 0.92,
        watermark_text_opacity: float = 0.85,
        subtitle_srt_path: Optional[str] = None,
        subtitle_animation: str = "fade",
        subtitle_font: str = "Be Vietnam Pro (Vietnamese)",
        subtitle_font_size: int = 56,
        subtitle_color: str = "#FFFFFF",
        subtitle_outline_color: str = "#000000",
        subtitle_outline_width: int = 3,
        subtitle_shadow: int = 0,
        subtitle_bold: bool = True,
        subtitle_italic: bool = False,
        subtitle_align: str = "center",
        subtitle_x: float = 0.5,
        subtitle_y: float = 0.85,
        subtitle_opacity: float = 1.0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        mute_source_videos: bool = True,
        transitions_pool: Optional[List[str]] = None,
        transition_duration: float = 0.5,
        ad_flip_random: bool = False,
        ad_flip_all: bool = False,
        ad_zoom: bool = False,
        ad_zoom_factor: float = 1.08,
        ad_color: bool = False,
        ad_saturation: float = 1.05,
        ad_contrast: float = 1.00,
        ad_gamma: float = 1.00,
        ad_hue_shift: float = 0.0,
        ad_clip_speed_jitter: bool = False,
        ad_clip_speed_jitter_range: float = 0.03,
        ad_strip_metadata: bool = False,
        visualizer_enabled: bool = False,
        visualizer_style: str = "bars",
        visualizer_x: float = 0.5,
        visualizer_y: float = 0.85,
        visualizer_w: int = 800,
        visualizer_h: int = 120,
        visualizer_color1: str = "#00E5FF",
        visualizer_color2: str = "#FF00FF",
        visualizer_opacity: float = 0.85,
        visualizer_bg_mode: str = "transparent",
        visualizer_bg_color: str = "#000000",
        visualizer_bg_opacity: float = 0.3,
        visualizer_spectrum_preset: str = "rainbow",
        visualizer_bars_mode: str = "bar",
        visualizer_waveform_mode: str = "cline",
        visualizer_waveform_mirror: bool = False,
        stickers: Optional[List[Dict]] = None,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.12,
        bgm_loop: bool = True,
        bgm_ducking: bool = True,
        bgm_fade: float = 2.0,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> Dict:
        """Render a short preview clip applying the full pipeline.

        Unlike process_story_video this does no DB lookup / writes, trims audio
        to min(audio_duration, max_duration) before atempo, and picks clips in
        folder filename order (no shuffle), looping if needed.
        """
        if not os.path.exists(audio_path):
            return {"success": False, "error": f"Audio not found: {audio_path}"}
        if not os.path.exists(video_source_folder):
            return {"success": False, "error": f"Folder not found: {video_source_folder}"}

        flip_mode = "all" if ad_flip_all else ("random" if ad_flip_random else "none")
        jitter = ad_clip_speed_jitter_range if ad_clip_speed_jitter else 0.0

        work_dir = output_path + ".work"
        os.makedirs(work_dir, exist_ok=True)

        try:
            def progress(pct: int) -> None:
                if progress_cb:
                    try:
                        progress_cb(pct)
                    except Exception:
                        pass

            full_audio_dur = self.get_media_duration(audio_path)
            if full_audio_dur <= 0:
                return {"success": False, "error": "Cannot determine audio duration"}
            preview_audio_dur = min(full_audio_dur, max_duration)

            trimmed_audio = os.path.join(work_dir, "preview_audio_trim.mp3")
            trim_a = self.trim_audio(audio_path, trimmed_audio, preview_audio_dur)
            if not trim_a["success"]:
                return trim_a
            progress(10)

            sped_audio = os.path.join(work_dir, "preview_audio_sped.mp3")
            speed_res = self.speed_up_audio(trimmed_audio, sped_audio, audio_speed)
            if not speed_res["success"]:
                return speed_res
            # Mix background music under the (trimmed + sped) narration so the
            # preview reflects the final audio. No-op when no BGM path is set.
            sped_audio, _bgm_warning = self._maybe_mix_bgm(
                sped_audio, work_dir,
                bgm_path, bgm_volume, bgm_loop, bgm_ducking, bgm_fade,
            )

            sped_dur = self.get_media_duration(sped_audio)
            if sped_dur <= 0:
                return {"success": False, "error": "Sped audio has zero duration"}
            progress(20)

            videos = self.get_all_videos_in_folder(video_source_folder, order="name")
            if not videos:
                return {"success": False, "error": "No video clips in folder"}

            picked: List[str] = []
            total = 0.0
            i = 0
            while total < sped_dur:
                v = videos[i % len(videos)]
                picked.append(v["path"])
                total += v["duration"]
                i += 1
            logger.info(f"Preview: picked {len(picked)} clips in order, total {total:.2f}s for {sped_dur:.2f}s sped audio")
            progress(30)

            # When a banner is used, concat at source aspect ratio so clips don't
            # bake black bars. Matches the production pipeline.
            concat_resolution = resolution
            if banner_image and os.path.exists(banner_image):
                src_w, src_h = self.get_video_dimensions(picked[0])
                if src_w > 0 and src_h > 0:
                    out_w, out_h = [int(x) for x in resolution.split('x')]
                    scale = min(out_w / src_w, out_h / src_h)
                    cw = int(src_w * scale) // 2 * 2
                    ch = int(src_h * scale) // 2 * 2
                    concat_resolution = f"{cw}x{ch}"

            ad_color_zoom_filter = self._build_ad_color_zoom_filter(
                *concat_resolution.split('x'),
                zoom=ad_zoom, zoom_factor=ad_zoom_factor,
                color=ad_color,
                saturation=ad_saturation, contrast=ad_contrast,
                gamma=ad_gamma, hue_shift=ad_hue_shift,
            )
            # Bound concat encode to sped_dur so ffmpeg stops at the right moment
            # — no separate trim pass needed for the trailing excess.
            concat_path = os.path.join(work_dir, "preview_concat.mp4")
            concat_res = self.concatenate_videos_from_folder(
                picked, concat_path, concat_resolution,
                keep_audio=not mute_source_videos,
                transitions_pool=transitions_pool,
                transition_duration=transition_duration,
                flip_mode=flip_mode,
                clip_speed_jitter=jitter,
                ad_color_zoom_filter=ad_color_zoom_filter,
                max_duration=sped_dur,
            )
            if not concat_res["success"]:
                return concat_res
            progress(65)

            video_for_merge = concat_path
            if banner_image and os.path.exists(banner_image):
                composite = os.path.join(work_dir, "preview_composite.mp4")
                overlay_res = self.overlay_on_banner(
                    concat_path, banner_image, composite,
                    resolution, sped_dur, banner_video_scale,
                    banner_video_offset_x, banner_video_offset_y,
                    scale_x=banner_video_scale_x, scale_y=banner_video_scale_y,
                )
                if not overlay_res["success"]:
                    return overlay_res
                video_for_merge = composite
            progress(75)

            # visualizer goes before watermark/subtitle so they sit on top.
            post_steps: List[str] = []
            if overlay_opacity > 0:
                post_steps.append("overlay")
            if visualizer_enabled:
                post_steps.append("visualizer")
            if watermark_image and os.path.exists(watermark_image):
                post_steps.append("watermark")
            if stickers and any(s.get("image_path") and os.path.exists(s["image_path"]) for s in stickers):
                post_steps.append("stickers")
            if subtitle_srt_path and os.path.exists(subtitle_srt_path):
                post_steps.append("subtitle")
            if watermark_text and watermark_text.strip():
                post_steps.append("text_watermark")
            if fade_in > 0 or fade_out > 0:
                post_steps.append("fade")
            if ad_strip_metadata:
                post_steps.append("ad_strip_metadata")

            merged_target = output_path if not post_steps else os.path.join(work_dir, "preview_merged.mp4")
            merge_res = self.merge_audio_video(video_for_merge, sped_audio, merged_target)
            if not merge_res["success"]:
                return merge_res
            progress(85)

            current = merged_target
            for idx, step in enumerate(post_steps):
                is_last = idx == len(post_steps) - 1
                next_path = output_path if is_last else os.path.join(work_dir, f"preview_post_{step}.mp4")
                if step == "overlay":
                    sr = self.apply_overlay(current, next_path, overlay_opacity, resolution)
                elif step == "visualizer":
                    sr = self.apply_visualizer(
                        current, next_path, sped_audio,
                        visualizer_style, visualizer_x, visualizer_y,
                        visualizer_w, visualizer_h,
                        visualizer_color1, visualizer_color2, visualizer_opacity,
                        visualizer_bg_mode, visualizer_bg_color, visualizer_bg_opacity,
                        visualizer_spectrum_preset, resolution,
                        bars_mode=visualizer_bars_mode,
                        waveform_mode=visualizer_waveform_mode,
                        waveform_mirror=visualizer_waveform_mirror,
                    )
                elif step == "watermark":
                    sr = self.apply_watermark(
                        current, next_path, watermark_image,
                        watermark_x, watermark_y,
                        watermark_w, watermark_h, watermark_shape,
                        watermark_opacity, resolution,
                    )
                elif step == "stickers":
                    sr = self.apply_stickers(
                        current, next_path, stickers or [], resolution,
                    )
                elif step == "text_watermark":
                    from app.services.fonts import ensure_font
                    font_name, font_path = ensure_font(watermark_text_font)
                    sr = self.apply_text_watermark(
                        current, next_path, watermark_text, font_path, font_name,
                        watermark_text_size, watermark_text_color, watermark_text_angle,
                        watermark_text_x, watermark_text_y,
                        watermark_text_opacity, resolution,
                    )
                elif step == "subtitle":
                    from app.services.fonts import ensure_font
                    sub_font_name, _ = ensure_font(subtitle_font)
                    sr = self.apply_subtitle(
                        current, next_path, subtitle_srt_path,
                        {
                            "font_name": sub_font_name,
                            "font_size": subtitle_font_size,
                            "color": subtitle_color,
                            "outline_color": subtitle_outline_color,
                            "outline_width": subtitle_outline_width,
                            "shadow": subtitle_shadow,
                            "bold": subtitle_bold,
                            "italic": subtitle_italic,
                            "align": subtitle_align,
                            "x": subtitle_x,
                            "y": subtitle_y,
                            "opacity": subtitle_opacity,
                        },
                        subtitle_animation, resolution,
                    )
                elif step == "fade":
                    sr = self.apply_fade(current, next_path, fade_in, fade_out)
                elif step == "ad_strip_metadata":
                    sr = self.strip_metadata(current, next_path)
                else:
                    continue
                if not sr["success"]:
                    return sr
                current = next_path
            progress(95)

            final_dur = self.get_media_duration(output_path)
            final_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            progress(100)
            return {
                "success": True,
                "output_path": output_path,
                "duration": final_dur,
                "file_size": final_size,
            }
        finally:
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

    def _create_temp_folder(
        self, output_dir: str, video_source_folder: str, target_duration: float,
        clip_order: str = "shuffle",
    ) -> str:
        """
        Re-scan the source folder and create a fresh, uniquely-named temp folder.
        Temp folders are named like: temp_20260225_143022_ab12cd34

        No reuse: the source folder is re-read every render. The caller deletes
        this folder when the render finishes (see process_story_video's finally),
        so temp clips don't accumulate on disk. The name includes a random suffix
        so two concurrent renders for the same story never share a folder — a
        blanket "delete all temp_* dirs" would otherwise wipe another in-flight
        job's freshly-copied clips.

        clip_order: "shuffle" (random order each render — different videos get
        different backgrounds) or "name" (filename A→Z, reproducible).
        """
        # Create a new temp folder with a unique name (timestamp alone can
        # collide within the same second across concurrent jobs).
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_folder = os.path.join(output_dir, f"temp_{timestamp}_{uuid.uuid4().hex[:8]}")

        logger.info(f"Creating new temp folder: {temp_folder}")

        # Scan source folder and select videos. Order is "shuffle" (random each
        # render) or "name" (filename A→Z). Loop the list when the total duration
        # is short of the target — final concat is trimmed to exact audio length
        # downstream, so the last clip may be cut mid-frame.
        order = "name" if clip_order == "name" else "shuffle"
        videos = self.get_all_videos_in_folder(video_source_folder, order=order)
        if not videos:
            raise ValueError(f"No videos found in source folder: {video_source_folder}")

        selected: List[Dict] = []
        total = 0.0
        i = 0
        while total < target_duration:
            v = videos[i % len(videos)]
            selected.append(v)
            total += v.get("duration", 0.0)
            i += 1
            # Hard stop in case every clip has 0 duration to prevent infinite loop.
            if i > len(videos) * 1000:
                break
        logger.info(
            f"Selected {len(selected)} video clips in {order} order "
            f"({total:.1f}s) for target {self._format_duration(target_duration)}"
        )

        # Copy to temp folder
        self.copy_to_temp_folder(selected, temp_folder)

        return temp_folder
