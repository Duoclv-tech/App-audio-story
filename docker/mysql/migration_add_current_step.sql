-- Migration: Add current_step column to stories table
-- Date: 2025-10-16
-- Description: Add current_step field to track workflow progress

USE truyenfull_db;

-- Check if column exists and add if it doesn't
-- Using a procedure to handle the conditional logic
DELIMITER $$

DROP PROCEDURE IF EXISTS add_current_step_column$$

CREATE PROCEDURE add_current_step_column()
BEGIN
    IF NOT EXISTS (
        SELECT * FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'truyenfull_db'
        AND TABLE_NAME = 'stories'
        AND COLUMN_NAME = 'current_step'
    ) THEN
        ALTER TABLE stories
        ADD COLUMN current_step INT DEFAULT 1 AFTER status;

        SELECT 'Column current_step added successfully!' as message;
    ELSE
        SELECT 'Column current_step already exists, skipping.' as message;
    END IF;
END$$

DELIMITER ;

-- Execute the procedure
CALL add_current_step_column();

-- Clean up
DROP PROCEDURE add_current_step_column;

-- Update existing records based on their current status
UPDATE stories
SET current_step = CASE
    WHEN status = 'draft' THEN 1
    WHEN status = 'created' THEN 1
    WHEN status = 'downloaded' THEN 3
    WHEN status = 'ready_for_tts' THEN 4
    WHEN status = 'tts_completed' THEN 6
    WHEN status = 'completed' THEN 7
    ELSE 1
END
WHERE current_step IS NULL OR current_step = 0;

-- Success message
SELECT 'Migration completed: current_step column added successfully!' as message;
