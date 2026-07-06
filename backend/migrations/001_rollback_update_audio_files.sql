-- Rollback Migration: Revert audio_files table changes
-- Date: 2025-10-16
-- Description: Remove TTS tracking columns and revert to original schema
-- WARNING: This will delete data in request_id, audio_link, error_message, updated_at columns

-- Drop indexes
DROP INDEX IF EXISTS idx_audio_files_status ON audio_files;
DROP INDEX IF EXISTS idx_audio_files_chapter_id ON audio_files;

-- Remove added columns
ALTER TABLE audio_files
  DROP COLUMN IF EXISTS request_id,
  DROP COLUMN IF EXISTS audio_link,
  DROP COLUMN IF EXISTS error_message,
  DROP COLUMN IF EXISTS updated_at;

-- Revert status default value
ALTER TABLE audio_files
  MODIFY COLUMN status VARCHAR(50) DEFAULT 'pending' COMMENT 'Status: pending, completed, failed';

-- Revert file_path to NOT NULL (WARNING: This may fail if there are NULL values)
-- ALTER TABLE audio_files
--   MODIFY COLUMN file_path TEXT NOT NULL COMMENT 'Path to audio file';

-- Update status back to 'pending' for records with 'idle' status
UPDATE audio_files SET status = 'pending' WHERE status = 'idle';
