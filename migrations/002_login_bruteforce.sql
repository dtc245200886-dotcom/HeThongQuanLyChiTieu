-- Brute-force protection for user login.
-- MySQL 8.0+; run after the users table exists.
SET NAMES utf8mb4;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS failed_login_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until DATETIME NULL;

