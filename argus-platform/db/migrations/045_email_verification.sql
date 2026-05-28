-- Migration 045: Email Verification Support
-- Adds columns to support email verification flow for new signups.
--
-- This prevents:
--   1. OAuth account takeover via unverified email signup (H-06)
--   2. Silently created user accounts with no verification
--   3. Compromised OAuth sessions granting immediate Argus access
--
-- Verification flow:
--   1. User signs up (credentials or OAuth)
--   2. Account created with email_verified = false
--   3. Verification email sent with code
--   4. User enters code on /auth/verify page
--   5. Account marked email_verified = true

-- Add email verification columns to users table
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(64),
    ADD COLUMN IF NOT EXISTS email_verification_token_expires TIMESTAMP WITH TIME ZONE;

-- Index for fast lookup by verification token
CREATE INDEX IF NOT EXISTS idx_users_email_verification_token
    ON users(email_verification_token)
    WHERE email_verification_token IS NOT NULL;

-- Index for querying unverified users
CREATE INDEX IF NOT EXISTS idx_users_email_verified
    ON users(email_verified)
    WHERE email_verified = false;

COMMENT ON COLUMN users.email_verified IS 'Whether the user has verified their email address';
COMMENT ON COLUMN users.email_verification_token IS 'Cryptographically secure token for email verification';
COMMENT ON COLUMN users.email_verification_token_expires IS 'Expiration timestamp for the verification token';

-- Verify existing users are grandfathered in (they existed before this policy)
UPDATE users SET email_verified = true WHERE email_verified IS NULL;
