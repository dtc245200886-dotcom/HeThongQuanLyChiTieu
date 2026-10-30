-- Password reset tokens for self-service password recovery.
-- SQLite: application startup creates the table from SQLAlchemy metadata.
-- MySQL 8.0+:
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    token_hash VARCHAR(128) NOT NULL,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_password_reset_token_hash (token_hash),
    KEY ix_password_reset_user_id (user_id),
    KEY ix_password_reset_expires_at (expires_at),
    CONSTRAINT fk_password_reset_user
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE saving_goals ADD COLUMN IF NOT EXISTS congratulated BOOLEAN NOT NULL DEFAULT FALSE;
