from pydantic import BaseModel, HttpUrl, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime

# Story Schemas
class StoryBase(BaseModel):
    title: str
    url: str
    author: Optional[str] = None
    total_chapters: Optional[int] = None
    start_chapter: int = 1
    end_chapter: Optional[int] = None
    custom_chapter_urls: Optional[List[str]] = None  # List of custom URLs for manual input

class StoryCreate(StoryBase):
    auto_check: bool = True
    auto_tts: bool = False

class StoryUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    author: Optional[str] = None
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    custom_chapter_urls: Optional[List[str]] = None
    status: Optional[str] = None
    current_step: Optional[int] = None
    tts_config: Optional[dict] = None

class StoryResponse(StoryBase):
    id: str
    status: str
    current_step: int
    is_favorite: bool = False
    tts_config: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class StoryWithStats(StoryResponse):
    total_downloaded: int = 0
    total_audio_generated: int = 0
    has_merged_audio: bool = False

# Chapter Schemas
class ChapterBase(BaseModel):
    chapter_number: int
    title: Optional[str] = None
    content: Optional[str] = None

class ChapterCreate(ChapterBase):
    story_id: str

class ChapterUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None

# --- Import chapters (paste / file / folder), replaces the scraper flow -------
class ImportChapterItem(BaseModel):
    chapter_number: int
    title: Optional[str] = None
    content: Optional[str] = None

class ImportChaptersRequest(BaseModel):
    title: Optional[str] = None            # optionally rename the story
    chapters: List[ImportChapterItem]

class ImportPathRequest(BaseModel):
    path: str
    title: Optional[str] = None

class CheckGrammarRequest(BaseModel):
    content: str

class ChapterResponse(ChapterBase):
    id: str
    story_id: str
    char_count: int
    has_censored_words: bool
    censored_count: int
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Audio Schemas
class AudioFileBase(BaseModel):
    file_path: str
    file_size: Optional[int] = None
    duration: Optional[float] = None
    format: str = 'mp3'
    bitrate: str = '192k'

class AudioFileCreate(AudioFileBase):
    chapter_id: str

class AudioFileResponse(AudioFileBase):
    id: str
    chapter_id: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

# Merged Audio Schemas
class MergedAudioResponse(BaseModel):
    id: str
    story_id: str
    file_path: str
    file_size: Optional[int]
    duration: Optional[float]
    format: str
    total_chapters: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True

# Task Schemas
class TaskBase(BaseModel):
    type: str
    total_items: Optional[int] = None

class TaskCreate(TaskBase):
    story_id: Optional[str] = None

class TaskResponse(TaskBase):
    id: str
    story_id: Optional[str]
    status: str
    progress: int
    completed_items: int
    failed_items: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

# Censored Word Schemas
class CensoredWordBase(BaseModel):
    word: str
    line_number: Optional[int]
    context: Optional[str]

class CensoredWordResponse(CensoredWordBase):
    id: str
    chapter_id: str
    fixed: bool
    word_type: str = 'censored'  # 'censored' or 'banned'
    suggested_replacement: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# Download Request
class DownloadRequest(BaseModel):
    story_id: str

class DownloadResponse(BaseModel):
    task_id: str
    status: str
    message: str

# TTS Request
class TTSRequest(BaseModel):
    story_id: str
    voice: str = "minh_khanh"
    speed: float = 1.0
    volume: int = 100

    # Engine selection: "vbee" (cloud, default) or "ai_voice_local" (local GPU)
    engine: str = "vbee"

    # VBEE / shared audio config
    voice_code: Optional[str] = None
    audio_type: str = "mp3"
    bitrate: int = 128

    # AI Voice local-only config
    mode: str = "auto"                 # auto | clone | design
    model_key: Optional[str] = None    # base
    preset_id: Optional[str] = None    # clone voice preset
    ref_text: Optional[str] = None     # inline reference transcript (clone)
    instruct: Optional[str] = None     # voice description (design)
    language: str = "Auto"             # Auto | Vietnamese | English

    # Per-segment run only: when true, also reset already-done segments back to
    # 'pending' (dropping their old audio) so EVERY sentence is re-synthesised
    # with the current config — used by the "Tạo lại toàn bộ" button after a
    # voice/setting change. Ignored by all other endpoints.
    regenerate_all: bool = False

class TTSResponse(BaseModel):
    task_id: str
    status: str
    message: str


# ---- Per-segment TTS (AI Voice local) ----
# Split / run / retry all carry the full TTSRequest config (engine/preset/lang/
# speed/bitrate) so the *current* config is applied when generating — not a
# stale snapshot. Run & retry reuse TTSRequest directly.
class SegmentSplitRequest(TTSRequest):
    split_mode: str = "newline"        # newline | period

class SegmentMergeRequest(BaseModel):
    story_id: str

# Audio Merge Request
class AudioMergeRequest(BaseModel):
    story_id: str
    output_format: str = "mp3"
    bitrate: str = "192k"
    crossfade: int = 0

class AudioMergeResponse(BaseModel):
    task_id: str
    status: str
    message: str

# Settings
class SettingResponse(BaseModel):
    id: int
    setting_key: str
    # Values are arbitrary JSON scalars/objects (string tokens, bool flags,
    # paths…), not only dicts — typing as dict 500s on every scalar setting.
    setting_value: Any = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Stats Response
class StoryStatsResponse(BaseModel):
    total_chapters: int
    total_characters: int
    chapters_over_9500: int
    chapters_under_9500: int
    total_censored_words: int
    chapters_with_censored: int
    estimated_duration: str
    estimated_cost: str

# Text Check Response
class TextCheckResponse(BaseModel):
    total_files: int
    files_over_9500: int
    files_under_9500: int
    files_with_censored: int
    total_censored_words: int

# Banned Word Schemas
class BannedWordBase(BaseModel):
    banned_word: str
    replacement_word: str
    description: Optional[str] = None
    is_active: bool = True

class BannedWordCreate(BannedWordBase):
    pass

class BannedWordUpdate(BaseModel):
    banned_word: Optional[str] = None
    replacement_word: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class BannedWordResponse(BannedWordBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Pagination Schemas
class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int

class PaginatedStoriesResponse(BaseModel):
    data: List[StoryWithStats]
    meta: PaginationMeta

class StoryOverviewResponse(BaseModel):
    total_projects: int
    total_audio_generated: int
    running_count: int

class PaginatedBannedWordsResponse(BaseModel):
    data: List['BannedWordResponse']
    meta: PaginationMeta

# Prompt Schemas
class PromptBase(BaseModel):
    title: str
    content: str
    category: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

class PromptCreate(PromptBase):
    pass

class PromptUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class PromptResponse(PromptBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PaginatedPromptsResponse(BaseModel):
    data: List['PromptResponse']
    meta: PaginationMeta

# Video Processing Schemas
class Sticker(BaseModel):
    """A single sticker (image or animated GIF/WebP/APNG) overlaid on the video.

    Position is center-based in normalized 0..1 coords (so it lays out the same
    across resolutions). end_time=None means "show until end of video".
    """
    image_path: str
    x: float = 0.5
    y: float = 0.5
    w: int = 200
    h: int = 200
    opacity: float = 1.0
    rotation: float = 0.0  # Clockwise rotation in degrees (0..360)
    start_time: float = 0.0
    end_time: Optional[float] = None

class VideoProcessRequest(BaseModel):
    story_id: str
    video_source_folder: str
    audio_path: Optional[str] = None  # Custom audio path (skip DB lookup if provided)
    clip_order: Literal["shuffle", "name"] = "shuffle"  # How to pick background clips: "shuffle" (random each render) | "name" (filename A→Z, reproducible)
    clip_seed: Optional[int] = None  # Shuffle seed shared by preview + final render so both produce the same clip order (None = random)
    audio_speed: float = 1.07
    transition_effect: str = "crossfade"
    transitions_pool: Optional[List[str]] = None  # Multi-select pool; overrides transition_effect if set
    transition_duration: float = 0.5
    resolution: str = "1920x1080"
    banner_image: Optional[str] = None  # Optional banner image as background
    banner_video_scale: float = 1.0  # Video size relative to banner (0.5 ~ 1.0)
    banner_video_offset_x: float = 0.0  # Horizontal offset from center, fraction of frame width (-0.5..0.5)
    banner_video_offset_y: float = 0.0  # Vertical offset from center, fraction of frame height (-0.5..0.5)
    banner_video_scale_x: Optional[float] = None  # Video width as fraction of frame; falls back to banner_video_scale
    banner_video_scale_y: Optional[float] = None  # Video height as fraction of frame; falls back to banner_video_scale
    banner_video_rotation: float = 0.0  # Clockwise rotation of the composited video, degrees (-180..180)
    overlay_opacity: float = 0.0  # Black overlay on top of composed video (0.0 = none, 0.8 = heavy)
    watermark_image: Optional[str] = None  # Optional watermark/logo image
    watermark_x: float = 0.92  # Center x in 0..1 (relative to frame)
    watermark_y: float = 0.92  # Center y in 0..1
    watermark_w: int = 200  # Width in px at output resolution
    watermark_h: int = 200  # Height in px
    watermark_shape: str = "none"  # none | circle | rounded | star | sun
    watermark_opacity: float = 0.85  # Watermark alpha (0.1 ~ 1.0)
    watermark_text: Optional[str] = None  # Optional text watermark
    watermark_text_font: str = "DejaVu Sans (system default)"
    watermark_text_size: int = 48  # px at output resolution
    watermark_text_color: str = "#FFFFFF"
    watermark_text_angle: float = 0.0  # rotation degrees, -45 ~ 45
    watermark_text_x: float = 0.92  # Center x in 0..1
    watermark_text_y: float = 0.92  # Center y in 0..1
    watermark_text_opacity: float = 0.85
    # Subtitle (burned-in SRT with style + animation)
    subtitle_srt_path: Optional[str] = None
    subtitle_animation: str = "fade"  # none | fade | pop | slide_up | typewriter
    subtitle_font: str = "Be Vietnam Pro (Vietnamese)"
    subtitle_font_size: int = 56
    subtitle_color: str = "#FFFFFF"
    subtitle_outline_color: str = "#000000"
    subtitle_outline_width: int = 3
    subtitle_shadow: int = 0
    subtitle_bold: bool = True
    subtitle_italic: bool = False
    subtitle_align: str = "center"  # left | center | right
    subtitle_x: float = 0.5
    subtitle_y: float = 0.85
    subtitle_opacity: float = 1.0
    subtitle_max_width: float = 0.9  # wrap box width as a fraction of frame (0..1)
    fade_in: float = 0.0  # Fade-in seconds at start (0 = none)
    fade_out: float = 0.0  # Fade-out seconds at end (0 = none)
    mute_source_videos: bool = True  # If True, drop audio from background clips (only main audio plays)

    # Background music (BGM) — mixed under the main narration. Default OFF (no path).
    bgm_path: Optional[str] = None      # Path to a music file; None/empty = no BGM
    bgm_volume: float = 0.12            # Music gain relative to narration (0.0 .. 1.0)
    bgm_loop: bool = True               # Loop music to fill the whole narration
    bgm_ducking: bool = True            # Auto lower music while narration plays (sidechain)
    bgm_fade: float = 2.0               # Fade-in/out seconds for the music (0 = none)

    # Stickers (image / GIF / WebP / APNG overlays at fixed positions+time ranges)
    stickers: List[Sticker] = []

    # Audio visualizer (default OFF) — overlay rendered from audio
    visualizer_enabled: bool = False
    # Style: bars | waveform | spectrum | cqt
    visualizer_style: str = "bars"
    visualizer_x: float = 0.5                  # Center x in 0..1
    visualizer_y: float = 0.85                 # Center y in 0..1
    visualizer_w: int = 800                    # px at output resolution
    visualizer_h: int = 120                    # px
    visualizer_color1: str = "#00E5FF"         # Primary color (hex)
    visualizer_color2: str = "#FF00FF"         # Secondary color (bars gradient)
    visualizer_opacity: float = 0.85
    visualizer_bg_mode: str = "transparent"    # "transparent" | "solid"
    visualizer_bg_color: str = "#000000"
    visualizer_bg_opacity: float = 0.3
    visualizer_spectrum_preset: str = "rainbow"  # showspectrum color preset
    # Sub-modes
    visualizer_bars_mode: str = "bar"          # bar | line | dot (showfreqs mode)
    visualizer_bars_mirror: bool = False       # If True, mirror bars center-out (bar mode only)
    visualizer_waveform_mode: str = "cline"    # cline | line | point | p2p (showwaves mode)
    visualizer_waveform_mirror: bool = False   # If True, vstack a vertically-flipped copy

    # Anti-detection (all default OFF)
    ad_flip_random: bool = False        # Mỗi clip 50% xác suất hflip
    ad_flip_all: bool = False           # Hflip toàn bộ clip (mutex với ad_flip_random)
    ad_zoom: bool = False
    ad_zoom_factor: float = 1.08        # 1.00..1.15
    ad_color: bool = False
    ad_saturation: float = 1.05         # 0.85..1.15
    ad_contrast: float = 1.00           # 0.90..1.10
    ad_gamma: float = 1.00              # 0.90..1.10
    ad_hue_shift: float = 0.0           # -15..15 deg
    ad_clip_speed_jitter: bool = False
    ad_clip_speed_jitter_range: float = 0.03  # ±0..0.05
    ad_strip_metadata: bool = False

    @model_validator(mode="after")
    def _ad_flip_mutex(self):
        if self.ad_flip_random and self.ad_flip_all:
            raise ValueError("ad_flip_random and ad_flip_all are mutually exclusive")
        return self

    @model_validator(mode="after")
    def _visualizer_options(self):
        valid_styles = {"bars", "waveform", "spectrum", "cqt"}
        if self.visualizer_style not in valid_styles:
            raise ValueError(f"visualizer_style must be one of: {sorted(valid_styles)}")
        if self.visualizer_bg_mode not in {"transparent", "solid"}:
            raise ValueError("visualizer_bg_mode must be one of: transparent, solid")
        if self.visualizer_bars_mode not in {"bar", "line", "dot"}:
            raise ValueError("visualizer_bars_mode must be one of: bar, line, dot")
        if self.visualizer_waveform_mode not in {"cline", "line", "point", "p2p"}:
            raise ValueError("visualizer_waveform_mode must be one of: cline, line, point, p2p")
        return self

class VideoProcessResponse(BaseModel):
    task_id: str
    status: str
    message: str

class VideoFolderValidateRequest(BaseModel):
    folder_path: str

class VideoFolderValidateResponse(BaseModel):
    valid: bool
    video_count: int = 0
    total_duration: float = 0
    total_duration_formatted: str = ""
    error: Optional[str] = None

class BrowseFolderRequest(BaseModel):
    path: str = ""

class BrowseFolderResponse(BaseModel):
    current_path: str
    parent_path: Optional[str] = None
    folders: List[str] = []
    video_count: int = 0

class BrowseFilesResponse(BaseModel):
    current_path: str
    parent_path: Optional[str] = None
    folders: List[str] = []
    files: List[str] = []

class VideoOutputResponse(BaseModel):
    id: str
    story_id: str
    audio_source_path: Optional[str]
    video_source_folder: Optional[str]
    output_path: Optional[str]
    file_size: Optional[int]
    duration: Optional[float]
    audio_speed: float
    transition_effect: str
    transition_duration: float
    resolution: str
    status: str
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Video Preset Schemas
class VideoPresetCreate(BaseModel):
    name: str
    cfg: Dict[str, Any]

class VideoPresetUpdate(BaseModel):
    name: Optional[str] = None
    cfg: Optional[Dict[str, Any]] = None

class VideoPresetResponse(BaseModel):
    id: str
    name: str
    cfg: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---- Build Preset (full quick-build preset) --------------------------------
class BuildPresetCreate(BaseModel):
    name: str
    tts_config: Dict[str, Any]
    cfg: Optional[Dict[str, Any]] = None          # FE videoConfig (wizard reload)
    video_cfg: Dict[str, Any]
    video_folder: Optional[str] = None
    bgm_path: Optional[str] = None
    watermark_image: Optional[str] = None
    banner_mode: str = "by_filename"
    banner_fixed: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class BuildPresetUpdate(BaseModel):
    name: Optional[str] = None
    tts_config: Optional[Dict[str, Any]] = None
    cfg: Optional[Dict[str, Any]] = None
    video_cfg: Optional[Dict[str, Any]] = None
    video_folder: Optional[str] = None
    bgm_path: Optional[str] = None
    watermark_image: Optional[str] = None
    banner_mode: Optional[str] = None
    banner_fixed: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class BuildPresetResponse(BaseModel):
    id: str
    name: str
    tts_config: Dict[str, Any]
    cfg: Optional[Dict[str, Any]] = None
    video_cfg: Dict[str, Any]
    video_folder: Optional[str] = None
    bgm_path: Optional[str] = None
    watermark_image: Optional[str] = None
    banner_mode: str
    banner_fixed: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---- Quick Build (batch orchestration) -------------------------------------
class QuickBuildScanRequest(BaseModel):
    path: str


class QuickBuildScanItem(BaseModel):
    source_path: str
    title: str
    has_banner: bool


class QuickBuildJobIn(BaseModel):
    source_path: str
    title: Optional[str] = None
    selected: bool = True
    overrides: Optional[Dict[str, Any]] = None


class QuickBuildStartRequest(BaseModel):
    preset_id: str
    jobs: List[QuickBuildJobIn]


class QuickBuildJobOut(BaseModel):
    id: str
    order_index: int
    source_path: str
    title: Optional[str] = None
    story_id: Optional[str] = None
    stage: str
    status: str
    progress: int = 0                       # 0-100, live render % of the running job
    output_path: Optional[str] = None
    output_size: Optional[int] = None       # bytes, set once the video exists
    error_message: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QuickBuildBatchStatus(BaseModel):
    id: str
    status: str
    total: int
    jobs: List[QuickBuildJobOut]
