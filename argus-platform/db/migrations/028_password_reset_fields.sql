-- Migration: Add password reset fields to users table (Step 29)
-- Adds columns needed for password reset functionality

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS reset_token VARCHAR(255),
ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP WITH TIME ZONE;

-- Index for reset token lookups
CREATE INDEX IF NOT EXISTS idx_users_reset_token ON users(reset_token) WHERE reset_token IS NOT NULL;

COMMENT ON COLUMN users.reset_token IS 'Password reset token (hashed)';
COMMENT ON COLUMN users.reset_token_expires_at IS 'Reset token expiration timestamp';
