-- Migration 017: Add index on user_settings for fast lookups
--
-- NOTE: The user_settings table uses user_id (TEXT UNIQUE) and settings (JSONB).
-- The UNIQUE constraint on user_id already provides fast lookups by user_id.
-- SettingsRepository uses jsonb_set for individual setting keys, so no
-- separate covering index is needed.
--
-- Previously attempted to create an index on (user_email, key) but those
-- columns don't exist in the user_settings table — corrected here.
--
-- This migration is intentionally a no-op since the user_id UNIQUE
-- constraint provides sufficient index coverage for all queries.
-- See SettingsRepository for the actual query patterns.

-- No-op: user_id UNIQUE constraint already provides index coverage
SELECT 1;
