-- Notification type discriminator for goal and budget events.
SET NAMES utf8mb4;

ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS type VARCHAR(30) NOT NULL DEFAULT 'budget';