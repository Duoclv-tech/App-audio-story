"""
Video Processing Worker
Background task worker for creating video from audio + background clips
"""
import asyncio
from typing import Dict, Optional
from loguru import logger

from app.database import SessionLocal
from app.services.video_processor import VideoProcessor
from app import models


async def process_video_task(
    task_id: str,
    story_id: str,
    config: Optional[Dict] = None
) -> Dict:
    """
    Background task to process video for a story

    Args:
        task_id: Task ID for progress tracking
        story_id: Story ID
        config: Video configuration (video_source_folder, audio_speed, etc.)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting video processing task {task_id} for story {story_id}")

        # Free the OmniVoice model from VRAM before the GPU-heavy NVENC render —
        # otherwise the local TTS weights and FFmpeg's encoder contend for the
        # same GPU and can OOM. No-op if OmniVoice was never loaded (or no GPU).
        try:
            from app.services.omnivoice_processor import unload_model
            unload_model()
        except Exception as e:
            logger.warning(f"[video] omnivoice unload skipped: {e}")

        if config is None:
            config = {}

        video_source_folder = config.get("video_source_folder", "")
        audio_path = config.get("audio_path")
        clip_order = config.get("clip_order", "shuffle")
        clip_seed = config.get("clip_seed")
        audio_speed = config.get("audio_speed", 1.07)
        transition_effect = config.get("transition_effect", "crossfade")
        transitions_pool = config.get("transitions_pool")
        transition_duration = config.get("transition_duration", 0.5)
        resolution = config.get("resolution", "1920x1080")
        banner_image = config.get("banner_image")
        banner_video_scale = config.get("banner_video_scale", 1.0)
        banner_video_offset_x = config.get("banner_video_offset_x", 0.0)
        banner_video_offset_y = config.get("banner_video_offset_y", 0.0)
        banner_video_scale_x = config.get("banner_video_scale_x")
        banner_video_scale_y = config.get("banner_video_scale_y")
        banner_video_rotation = config.get("banner_video_rotation", 0.0)
        overlay_opacity = config.get("overlay_opacity", 0.0)
        watermark_image = config.get("watermark_image")
        watermark_x = config.get("watermark_x", 0.92)
        watermark_y = config.get("watermark_y", 0.92)
        watermark_w = config.get("watermark_w", 200)
        watermark_h = config.get("watermark_h", 200)
        watermark_shape = config.get("watermark_shape", "none")
        watermark_opacity = config.get("watermark_opacity", 0.85)
        watermark_text = config.get("watermark_text")
        watermark_text_font = config.get("watermark_text_font", "DejaVu Sans (system default)")
        watermark_text_size = config.get("watermark_text_size", 48)
        watermark_text_color = config.get("watermark_text_color", "#FFFFFF")
        watermark_text_angle = config.get("watermark_text_angle", 0.0)
        watermark_text_x = config.get("watermark_text_x", 0.92)
        watermark_text_y = config.get("watermark_text_y", 0.92)
        watermark_text_opacity = config.get("watermark_text_opacity", 0.85)
        subtitle_srt_path = config.get("subtitle_srt_path")
        subtitle_animation = config.get("subtitle_animation", "fade")
        subtitle_font = config.get("subtitle_font", "Be Vietnam Pro (Vietnamese)")
        subtitle_font_size = config.get("subtitle_font_size", 56)
        subtitle_color = config.get("subtitle_color", "#FFFFFF")
        subtitle_outline_color = config.get("subtitle_outline_color", "#000000")
        subtitle_outline_width = config.get("subtitle_outline_width", 3)
        subtitle_shadow = config.get("subtitle_shadow", 0)
        subtitle_bold = config.get("subtitle_bold", True)
        subtitle_italic = config.get("subtitle_italic", False)
        subtitle_align = config.get("subtitle_align", "center")
        subtitle_x = config.get("subtitle_x", 0.5)
        subtitle_y = config.get("subtitle_y", 0.85)
        subtitle_opacity = config.get("subtitle_opacity", 1.0)
        fade_in = config.get("fade_in", 0.0)
        fade_out = config.get("fade_out", 0.0)
        mute_source_videos = config.get("mute_source_videos", True)
        ad_flip_random = config.get("ad_flip_random", False)
        ad_flip_all = config.get("ad_flip_all", False)
        ad_zoom = config.get("ad_zoom", False)
        ad_zoom_factor = config.get("ad_zoom_factor", 1.08)
        ad_color = config.get("ad_color", False)
        ad_saturation = config.get("ad_saturation", 1.05)
        ad_contrast = config.get("ad_contrast", 1.00)
        ad_gamma = config.get("ad_gamma", 1.00)
        ad_hue_shift = config.get("ad_hue_shift", 0.0)
        ad_clip_speed_jitter = config.get("ad_clip_speed_jitter", False)
        ad_clip_speed_jitter_range = config.get("ad_clip_speed_jitter_range", 0.03)
        ad_strip_metadata = config.get("ad_strip_metadata", False)
        visualizer_enabled = config.get("visualizer_enabled", False)
        visualizer_style = config.get("visualizer_style", "bars")
        visualizer_x = config.get("visualizer_x", 0.5)
        visualizer_y = config.get("visualizer_y", 0.85)
        visualizer_w = config.get("visualizer_w", 800)
        visualizer_h = config.get("visualizer_h", 120)
        visualizer_color1 = config.get("visualizer_color1", "#00E5FF")
        visualizer_color2 = config.get("visualizer_color2", "#FF00FF")
        visualizer_opacity = config.get("visualizer_opacity", 0.85)
        visualizer_bg_mode = config.get("visualizer_bg_mode", "transparent")
        visualizer_bg_color = config.get("visualizer_bg_color", "#000000")
        visualizer_bg_opacity = config.get("visualizer_bg_opacity", 0.3)
        visualizer_spectrum_preset = config.get("visualizer_spectrum_preset", "rainbow")
        visualizer_bars_mode = config.get("visualizer_bars_mode", "bar")
        visualizer_waveform_mode = config.get("visualizer_waveform_mode", "cline")
        visualizer_waveform_mirror = config.get("visualizer_waveform_mirror", False)
        stickers = config.get("stickers") or []
        bgm_path = config.get("bgm_path")
        bgm_volume = config.get("bgm_volume", 0.12)
        bgm_loop = config.get("bgm_loop", True)
        bgm_ducking = config.get("bgm_ducking", True)
        bgm_fade = config.get("bgm_fade", 2.0)

        # Update task status
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task:
            task.status = "running"
            db.commit()

        # Create video processor
        processor = VideoProcessor()

        if not processor.ffmpeg_available:
            raise RuntimeError("FFmpeg is not installed. Please install FFmpeg for video processing.")

        # Process video
        result = processor.process_story_video(
            story_id=story_id,
            task_id=task_id,
            db=db,
            video_source_folder=video_source_folder,
            audio_path=audio_path,
            clip_order=clip_order,
            clip_seed=clip_seed,
            audio_speed=audio_speed,
            transition_effect=transition_effect,
            transitions_pool=transitions_pool,
            transition_duration=transition_duration,
            resolution=resolution,
            banner_image=banner_image,
            banner_video_scale=banner_video_scale,
            banner_video_offset_x=banner_video_offset_x,
            banner_video_offset_y=banner_video_offset_y,
            banner_video_scale_x=banner_video_scale_x,
            banner_video_scale_y=banner_video_scale_y,
            banner_video_rotation=banner_video_rotation,
            overlay_opacity=overlay_opacity,
            watermark_image=watermark_image,
            watermark_x=watermark_x,
            watermark_y=watermark_y,
            watermark_w=watermark_w,
            watermark_h=watermark_h,
            watermark_shape=watermark_shape,
            watermark_opacity=watermark_opacity,
            watermark_text=watermark_text,
            watermark_text_font=watermark_text_font,
            watermark_text_size=watermark_text_size,
            watermark_text_color=watermark_text_color,
            watermark_text_angle=watermark_text_angle,
            watermark_text_x=watermark_text_x,
            watermark_text_y=watermark_text_y,
            watermark_text_opacity=watermark_text_opacity,
            subtitle_srt_path=subtitle_srt_path,
            subtitle_animation=subtitle_animation,
            subtitle_font=subtitle_font,
            subtitle_font_size=subtitle_font_size,
            subtitle_color=subtitle_color,
            subtitle_outline_color=subtitle_outline_color,
            subtitle_outline_width=subtitle_outline_width,
            subtitle_shadow=subtitle_shadow,
            subtitle_bold=subtitle_bold,
            subtitle_italic=subtitle_italic,
            subtitle_align=subtitle_align,
            subtitle_x=subtitle_x,
            subtitle_y=subtitle_y,
            subtitle_opacity=subtitle_opacity,
            fade_in=fade_in,
            fade_out=fade_out,
            mute_source_videos=mute_source_videos,
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

        if result.get("success"):
            logger.info(f"Video processing task {task_id} completed successfully")
            logger.info(f"Output file: {result.get('output_path')}")
        else:
            logger.error(f"Video processing task {task_id} failed: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error in video processing task {task_id}: {e}")

        try:
            db.rollback()
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                task.status = "failed"
                task.error_message = str(e)
                db.commit()
        except Exception:
            db.rollback()

        return {"success": False, "error": str(e)}

    finally:
        db.close()


def run_video_task(task_id: str, story_id: str, config: Optional[Dict] = None):
    """
    Synchronous wrapper for running video task in a thread

    Args:
        task_id: Task ID
        story_id: Story ID
        config: Video configuration
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            process_video_task(task_id, story_id, config)
        )
        return result
    finally:
        loop.close()
