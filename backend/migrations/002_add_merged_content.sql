-- Migration: Add merged_content column to stories table
-- For storing all chapters merged into one text for editing

ALTER TABLE stories ADD COLUMN merged_content LONGTEXT NULL AFTER is_favorite;
