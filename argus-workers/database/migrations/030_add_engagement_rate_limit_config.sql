-- Migration 030: Add engagements.rate_limit_config
--
-- snapshot_manager and the engagement repository allowlist read/write
-- rate_limit_config, but no schema or migration created the column. Analysis
-- snapshot creation failed with UndefinedColumn on a fresh database.

ALTER TABLE engagements
  ADD COLUMN IF NOT EXISTS rate_limit_config JSONB DEFAULT '{}'::jsonb;
