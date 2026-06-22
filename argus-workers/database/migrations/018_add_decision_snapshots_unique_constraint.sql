-- Migration 018: Add unique constraint on decision_snapshots (engagement_id, version)
-- Hardens the snapshot race-condition fix from snapshot_manager.py.
-- Prevents duplicate version numbers when concurrent workers create snapshots
-- for the same engagement, providing data-integrity enforcement regardless
-- of application-level retry logic.

BEGIN;

-- Create table if it doesn't exist (some deployments may have missed the init)
CREATE TABLE IF NOT EXISTS decision_snapshots (
    id          UUID PRIMARY KEY,
    engagement_id UUID NOT NULL,
    version     INTEGER NOT NULL,
    snapshot_data JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add unique constraint using a DO block so it's idempotent:
-- if the constraint already exists, the exception is silently caught.
DO $$
BEGIN
    ALTER TABLE decision_snapshots
        ADD CONSTRAINT uq_decision_snapshots_engagement_version
        UNIQUE (engagement_id, version);
EXCEPTION
    WHEN duplicate_table THEN
        NULL;  -- constraint already exists
    WHEN duplicate_object THEN
        NULL;  -- constraint already exists (alternative error code)
END $$;

-- Index for the lookup pattern used by _store_snapshot:
--   SELECT COALESCE(MAX(version), 0) + 1 FROM decision_snapshots WHERE engagement_id = %s
CREATE INDEX IF NOT EXISTS idx_decision_snapshots_engagement_version
    ON decision_snapshots (engagement_id, version DESC);

COMMIT;

-- Down:
-- BEGIN;
--     ALTER TABLE decision_snapshots DROP CONSTRAINT IF EXISTS uq_decision_snapshots_engagement_version;
--     DROP INDEX IF EXISTS idx_decision_snapshots_engagement_version;
-- COMMIT;
