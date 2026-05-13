-- Migration 017: Add index on user_settings (user_email, key) for fast lookups
-- All get/set queries filter on WHERE user_email = %s AND key = %s — no covering index existed.
CREATE INDEX IF NOT EXISTS idx_user_settings_email_key
    ON user_settings(user_email, key);
