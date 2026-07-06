-- Create database if not exists
CREATE DATABASE IF NOT EXISTS truyenfull_db
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE truyenfull_db;

-- Stories table
CREATE TABLE IF NOT EXISTS stories (
    id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    url TEXT NOT NULL,
    author VARCHAR(255),
    total_chapters INT,
    start_chapter INT,
    end_chapter INT,
    status VARCHAR(50) DEFAULT 'created',
    current_step INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Chapters table
CREATE TABLE IF NOT EXISTS chapters (
    id VARCHAR(36) PRIMARY KEY,
    story_id VARCHAR(36) NOT NULL,
    chapter_number INT NOT NULL,
    title VARCHAR(500),
    content LONGTEXT,
    char_count INT DEFAULT 0,
    has_censored_words BOOLEAN DEFAULT FALSE,
    censored_count INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_story_chapter (story_id, chapter_number),
    FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
    INDEX idx_story_id (story_id),
    INDEX idx_chapter_number (chapter_number),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Audio files table
CREATE TABLE IF NOT EXISTS audio_files (
    id VARCHAR(36) PRIMARY KEY,
    chapter_id VARCHAR(36) NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT,
    duration FLOAT,
    format VARCHAR(10) DEFAULT 'mp3',
    bitrate VARCHAR(10) DEFAULT '192k',
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
    INDEX idx_chapter_id (chapter_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Merged audio table
CREATE TABLE IF NOT EXISTS merged_audio (
    id VARCHAR(36) PRIMARY KEY,
    story_id VARCHAR(36) NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT,
    duration FLOAT,
    format VARCHAR(10) DEFAULT 'mp3',
    total_chapters INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
    INDEX idx_story_id (story_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tasks table (background jobs tracking)
CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(36) PRIMARY KEY,
    story_id VARCHAR(36),
    type VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'queued',
    progress INT DEFAULT 0,
    total_items INT,
    completed_items INT DEFAULT 0,
    failed_items INT DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
    INDEX idx_story_id (story_id),
    INDEX idx_type (type),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Censored words tracking
CREATE TABLE IF NOT EXISTS censored_words (
    id VARCHAR(36) PRIMARY KEY,
    chapter_id VARCHAR(36) NOT NULL,
    word VARCHAR(255),
    line_number INT,
    context TEXT,
    fixed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
    INDEX idx_chapter_id (chapter_id),
    INDEX idx_fixed (fixed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Video outputs table
CREATE TABLE IF NOT EXISTS video_outputs (
    id VARCHAR(36) PRIMARY KEY,
    story_id VARCHAR(36) NOT NULL,
    audio_source_path TEXT,
    video_source_folder TEXT,
    output_path TEXT,
    file_size BIGINT,
    duration FLOAT,
    audio_speed FLOAT DEFAULT 1.07,
    transition_effect VARCHAR(50) DEFAULT 'crossfade',
    transition_duration FLOAT DEFAULT 0.5,
    resolution VARCHAR(20) DEFAULT '1920x1080',
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
    INDEX idx_story_id (story_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Settings table
CREATE TABLE IF NOT EXISTS settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value JSON,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_key (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default settings
INSERT INTO settings (setting_key, setting_value) VALUES
('tts_voice', '"minh_khanh"'),
('tts_speed', '1.0'),
('tts_volume', '100'),
('auto_check_grammar', 'true'),
('auto_run_tts', 'false'),
('audio_format', '"mp3"'),
('audio_bitrate', '"192k"')
ON DUPLICATE KEY UPDATE setting_key=setting_key;

-- Success message
SELECT 'Database initialized successfully!' as message;
