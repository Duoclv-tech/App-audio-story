from sqlalchemy import Column, String, Integer, Text, Boolean, Float, BigInteger, ForeignKey, TIMESTAMP, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class Story(Base):
    __tablename__ = "stories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(500), nullable=False)
    url = Column(Text, nullable=False)
    author = Column(String(255))
    total_chapters = Column(Integer)
    start_chapter = Column(Integer)
    end_chapter = Column(Integer)
    custom_chapter_urls = Column(JSON, nullable=True)  # List of custom URLs for chapters without pattern
    status = Column(String(50), default='created')
    current_step = Column(Integer, default=1)
    is_favorite = Column(Boolean, default=False)
    # Set when Quick Build creates this story → groups it under its batch in the
    # history feed. NULL = a normal, standalone story made through the wizard.
    batch_id = Column(String(36), nullable=True, index=True)
    merged_content = Column(Text, nullable=True)  # All chapters merged into one text
    tts_config = Column(JSON, nullable=True)  # Saved "Cấu hình TTS" step: engine + voice/settings
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    chapters = relationship("Chapter", back_populates="story", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="story", cascade="all, delete-orphan")
    merged_audio = relationship("MergedAudio", back_populates="story", cascade="all, delete-orphan")
    video_outputs = relationship("VideoOutput", back_populates="story", cascade="all, delete-orphan")
    tts_segments = relationship("TtsSegment", back_populates="story", cascade="all, delete-orphan")

class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    story_id = Column(String(36), ForeignKey('stories.id', ondelete='CASCADE'), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    title = Column(String(500))
    content = Column(Text)
    char_count = Column(Integer, default=0)
    has_censored_words = Column(Boolean, default=False)
    censored_count = Column(Integer, default=0)
    status = Column(String(50), default='pending')
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    story = relationship("Story", back_populates="chapters")
    audio_files = relationship("AudioFile", back_populates="chapter", cascade="all, delete-orphan")
    censored_words = relationship("CensoredWord", back_populates="chapter", cascade="all, delete-orphan")

class AudioFile(Base):
    __tablename__ = "audio_files"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    chapter_id = Column(String(36), ForeignKey('chapters.id', ondelete='CASCADE'), nullable=False)
    file_path = Column(Text, nullable=True)  # Nullable because initially no file yet
    file_size = Column(BigInteger)
    duration = Column(Float)
    format = Column(String(10), default='mp3')
    bitrate = Column(String(10), default='192k')
    status = Column(String(50), default='idle')  # idle, processing, success, failed
    request_id = Column(String(255), nullable=True)  # VBEE request ID
    audio_link = Column(Text, nullable=True)  # VBEE audio link
    error_message = Column(Text, nullable=True)  # Error if failed
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    chapter = relationship("Chapter", back_populates="audio_files")

class MergedAudio(Base):
    __tablename__ = "merged_audio"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    story_id = Column(String(36), ForeignKey('stories.id', ondelete='CASCADE'), nullable=False)
    file_path = Column(Text, nullable=False)
    file_size = Column(BigInteger)
    duration = Column(Float)
    format = Column(String(10), default='mp3')
    total_chapters = Column(Integer)
    engine = Column(String(20))  # 'vbee' | 'omnivoice' — which TTS engine produced this file
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    story = relationship("Story", back_populates="merged_audio")

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    story_id = Column(String(36), ForeignKey('stories.id', ondelete='CASCADE'))
    type = Column(String(50), nullable=False)
    engine = Column(String(20))  # 'vbee' | 'omnivoice' — which TTS engine this task belongs to
    status = Column(String(50), default='queued')
    progress = Column(Integer, default=0)
    total_items = Column(Integer)
    completed_items = Column(Integer, default=0)
    failed_items = Column(Integer, default=0)
    error_message = Column(Text)
    started_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    story = relationship("Story", back_populates="tasks")

class TtsSegment(Base):
    """One sentence/line of a story queued for OmniVoice TTS.

    Splitting the merged story into segments lets each line be generated,
    inspected, retried and re-listened to independently, then concatenated
    into one final audio. Persisted in DB so progress survives app restarts.
    """
    __tablename__ = "tts_segments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    story_id = Column(String(36), ForeignKey('stories.id', ondelete='CASCADE'), nullable=False, index=True)
    seg_index = Column(Integer, nullable=False)          # 1-based order
    text = Column(Text, nullable=False)
    status = Column(String(20), default='pending')       # pending | processing | done | error
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, default=0)
    file_path = Column(Text, nullable=True)              # mp3 for this segment
    file_size = Column(BigInteger, nullable=True)
    duration = Column(Float, nullable=True)              # audio seconds
    gen_sec = Column(Float, nullable=True)               # generation wall time
    split_mode = Column(String(10), default='newline')   # newline | period
    source_hash = Column(String(40), nullable=True)      # sha1 of merged_content at split time
    config = Column(JSON, nullable=True)                 # snapshot of ttsConfig (engine/preset/lang/speed/bitrate)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    story = relationship("Story", back_populates="tts_segments")


class CensoredWord(Base):
    __tablename__ = "censored_words"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    chapter_id = Column(String(36), ForeignKey('chapters.id', ondelete='CASCADE'), nullable=False)
    word = Column(String(255))
    line_number = Column(Integer)
    context = Column(Text)
    fixed = Column(Boolean, default=False)
    word_type = Column(String(50), default='censored')  # 'censored' or 'banned'
    suggested_replacement = Column(String(255))  # Suggested replacement word
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    chapter = relationship("Chapter", back_populates="censored_words")

class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    setting_key = Column(String(100), unique=True, nullable=False)
    setting_value = Column(JSON)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

class Voice(Base):
    __tablename__ = "voices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    gender = Column(String(10), nullable=False, index=True)
    locale = Column(String(20), nullable=False, index=True)
    category = Column(String(50))
    description = Column(Text)
    demo_url = Column(String(500))
    is_active = Column(Boolean, default=True, index=True)
    rank = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

class BannedWord(Base):
    __tablename__ = "banned_words"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    banned_word = Column(String(255), nullable=False, unique=True, index=True)
    replacement_word = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

class VideoOutput(Base):
    __tablename__ = "video_outputs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    story_id = Column(String(36), ForeignKey('stories.id', ondelete='CASCADE'))
    audio_source_path = Column(Text)
    video_source_folder = Column(Text)
    output_path = Column(Text)
    file_size = Column(BigInteger)
    duration = Column(Float)
    audio_speed = Column(Float, default=1.07)
    transition_effect = Column(String(50), default='crossfade')
    transition_duration = Column(Float, default=0.5)
    resolution = Column(String(20), default='1920x1080')
    status = Column(String(50), default='pending')
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    story = relationship("Story", back_populates="video_outputs")

class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=False, index=True)
    content = Column(Text, nullable=False)
    category = Column(String(100), index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class VideoPreset(Base):
    __tablename__ = "video_presets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, unique=True, index=True)
    cfg = Column(JSON, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class BuildPreset(Base):
    """The single unified preset used by BOTH the wizard's video step and Quick
    Build. Carries everything to turn a story into a finished video in one shot —
    TTS voice/engine, the video config in two shapes, the background-clip folder,
    plus per-run options.

    Two video representations are stored because the two consumers want different
    shapes: ``cfg`` is the wizard's FE videoConfig (so the wizard can reload the UI
    exactly), while ``video_cfg`` is the backend-flattened payload the render
    worker consumes (per-story paths nulled). Both are written at save time from
    the wizard, which has all the data. (Formerly VideoPreset held only ``cfg``;
    the two systems were merged — legacy video presets are migrated in with an
    empty ``video_cfg`` until re-saved.)
    """
    __tablename__ = "build_presets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, unique=True, index=True)
    tts_config = Column(JSON, nullable=False)     # {engine, voice_code, speed, bitrate, preset_id, mode, ...}
    cfg = Column(JSON, nullable=True)             # FE videoConfig (for the wizard to reload its UI)
    video_cfg = Column(JSON, nullable=False)      # backend-flattened video config (per-story paths nulled)
    video_folder = Column(Text, nullable=True)    # background-clip folder
    bgm_path = Column(Text, nullable=True)
    watermark_image = Column(Text, nullable=True)
    banner_mode = Column(String(20), default="by_filename")   # by_filename | none | fixed
    banner_fixed = Column(Text, nullable=True)
    options = Column(JSON, nullable=True)         # {skip_spellcheck, auto_clean, auto_subtitle}
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class BuildBatch(Base):
    """One 'quick build' run over a folder of story files."""
    __tablename__ = "build_batches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    status = Column(String(20), default="queued")   # queued | running | done | stopped
    total = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    jobs = relationship("BuildJob", back_populates="batch", cascade="all, delete-orphan")


class BuildJob(Base):
    """One story file in a batch → one video. Tracks which pipeline stage it's on
    so the frontend can render live progress and isolate per-file failures.
    """
    __tablename__ = "build_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    batch_id = Column(String(36), ForeignKey('build_batches.id', ondelete='CASCADE'), nullable=False, index=True)
    order_index = Column(Integer, default=0)
    source_path = Column(Text, nullable=False)
    title = Column(String(500))
    story_id = Column(String(36), nullable=True)   # filled once the Story row is created
    preset_id = Column(String(36), nullable=True)
    overrides = Column(JSON, nullable=True)        # per-job overrides merged over the preset
    stage = Column(String(20), default="create")   # create | tts | video | done
    status = Column(String(20), default="pending") # pending | running | done | error
    output_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    batch = relationship("BuildBatch", back_populates="jobs")
