-- Migration: Add is_favorite field to stories table
-- Date: 2025-11-27
-- Description: Add is_favorite boolean field to allow users to mark stories as favorites

-- Add is_favorite column
ALTER TABLE stories
ADD COLUMN is_favorite BOOLEAN DEFAULT FALSE AFTER current_step;

-- Update existing records to default false
UPDATE stories SET is_favorite = FALSE WHERE is_favorite IS NULL;
