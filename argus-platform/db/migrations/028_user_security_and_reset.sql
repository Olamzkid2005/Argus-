-- Migration: Add user security and password reset fields (Step 28)
-- Merged from 028_password_reset_fields.sql + 028_user_security_fields.sql
-- Combines 2FA/security columns and password reset columns into one migration
-- to resolve migration number conflict (both were numbered 028).

ALTER TABLE users 
  -- Security / 2FA fields
  ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(255),
  ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS password_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  -- Password reset fields
  ADD COLUMN IF NOT EXISTS reset_token VARCHAR(255),
  ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP WITH TIME ZONE;

-- Index for lockout lookups
CREATE INDEX IF NOT EXISTS idx_users_locked_until ON users(locked_until) WHERE locked_until IS NOT NULL;

-- Index for reset token lookups
CREATE INDEX IF NOT EXISTS idx_users_reset_token ON users(reset_token) WHERE reset_token IS NOT NULL;

COMMENT ON COLUMN users.two_factor_enabled IS 'Whether 2FA is enabled for this user';
COMMENT ON COLUMN users.totp_secret IS 'Encrypted TOTP secret for 2FA';
COMMENT ON COLUMN users.failed_login_attempts IS 'Number of failed login attempts';
COMMENT ON COLUMN users.locked_until IS 'Account locked until this timestamp';
COMMENT ON COLUMN users.password_updated_at IS 'Last password change timestamp';
COMMENT ON COLUMN users.reset_token IS 'Password reset token (hashed)';
COMMENT ON COLUMN users.reset_token_expires_at IS 'Reset token expiration timestamp';
