-- Migration: Update audio_files table for TTS tracking
-- Date: 2025-10-16
-- Description: Add request_id, audio_link, error_message columns and update status default value

-- Step 1: Add new columns for TTS tracking (one by one to avoid IF NOT EXISTS issue)
ALTER TABLE audio_files ADD COLUMN request_id VARCHAR(255) NULL COMMENT 'VBEE TTS request ID';
ALTER TABLE audio_files ADD COLUMN audio_link TEXT NULL COMMENT 'VBEE audio download link';
ALTER TABLE audio_files ADD COLUMN error_message TEXT NULL COMMENT 'Error message if processing failed';
ALTER TABLE audio_files ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp';

-- Step 2: Modify existing columns
ALTER TABLE audio_files MODIFY COLUMN file_path TEXT NULL COMMENT 'File path - nullable until audio is generated';
ALTER TABLE audio_files MODIFY COLUMN status VARCHAR(50) DEFAULT 'idle' COMMENT 'Status: idle, processing, success, failed';

-- Step 3: Update existing records with old status 'pending' to 'idle'
UPDATE audio_files SET status = 'idle' WHERE status = 'pending';
