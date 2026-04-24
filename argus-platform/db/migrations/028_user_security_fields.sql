-- Migration: Add 2FA/security fields to users table (Step 28)
-- Adds columns needed for TOTP 2FA and account security

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(255),
ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS password_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Index for lockout lookups
CREATE INDEX IF NOT EXISTS idx_users_locked_until ON users(locked_until) WHERE locked_until IS NOT NULL;

COMMENT ON COLUMN users.two_factor_enabled IS 'Whether 2FA is enabled for this user';
COMMENT ON COLUMN users.totp_secret IS 'Encrypted TOTP secret for 2FA';
COMMENT ON COLUMN users.failed_login_attempts IS 'Number of failed login attempts';
COMMENT ON COLUMN users.locked_until IS 'Account locked until this timestamp';
COMMENT ON COLUMN users.password_updated_at IS 'Last password change timestamp';