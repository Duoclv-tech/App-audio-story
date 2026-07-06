-- Migration: Add banned_words table and update censored_words table
-- Date: 2025-10-20

-- Create banned_words table
CREATE TABLE IF NOT EXISTS banned_words (
    id VARCHAR(36) PRIMARY KEY,
    banned_word VARCHAR(255) NOT NULL UNIQUE,
    replacement_word VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_banned_word (banned_word),
    INDEX idx_is_active (is_active)
);

-- Add new columns to censored_words table
ALTER TABLE censored_words
ADD COLUMN IF NOT EXISTS word_type VARCHAR(50) DEFAULT 'censored' COMMENT 'Type of word: censored or banned',
ADD COLUMN IF NOT EXISTS suggested_replacement VARCHAR(255) COMMENT 'Suggested replacement word';

-- Insert some sample banned words
INSERT INTO banned_words (id, banned_word, replacement_word, description, is_active) VALUES
(UUID(), 'chết', 'mất', 'Từ bị kiểm duyệt - thay bằng từ nhẹ hơn', TRUE),
(UUID(), 'cặc', '[bị kiểm duyệt]', 'Từ tục tĩu', TRUE),
(UUID(), 'lồn', '[bị kiểm duyệt]', 'Từ tục tĩu', TRUE),
(UUID(), 'đ*t', 'mông', 'Từ bị kiểm duyệt với ký tự đặc biệt', TRUE),
(UUID(), 'đít', 'mông', 'Từ bị kiểm duyệt', TRUE)
ON DUPLICATE KEY UPDATE
    replacement_word = VALUES(replacement_word),
    description = VALUES(description),
    updated_at = CURRENT_TIMESTAMP;

-- Migration complete
