-- Structured AI request history.
SET NAMES utf8mb4;

ALTER TABLE ai_logs
    ADD COLUMN IF NOT EXISTS question TEXT NULL,
    ADD COLUMN IF NOT EXISTS response_type VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NULL;
