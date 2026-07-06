-- Migration: Add video_outputs table
-- Date: 2026-02-25

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

-- Update existing completed stories to new step numbering
-- Stories at step 7 (was Complete) should now be at step 8
UPDATE stories SET current_step = 8 WHERE current_step = 7;
