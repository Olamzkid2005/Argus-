-- Migration 015: Add unique constraint for finding deduplication
-- Prevents duplicate findings from concurrent tools
--
-- M-v4-11: schema.sql already defines CONSTRAINT findings_dedup on the same
-- columns. Skip if either constraint already exists to avoid redundant
-- unique indexes that double write overhead on every INSERT/UPDATE.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname IN ('uq_finding_dedup', 'findings_dedup')
          AND conrelid = 'findings'::regclass
    ) THEN
        ALTER TABLE findings
        ADD CONSTRAINT uq_finding_dedup
        UNIQUE (engagement_id, endpoint, type, source_tool);
    END IF;
END $$;

COMMENT ON CONSTRAINT uq_finding_dedup ON findings IS
    'Prevents duplicate findings with the same engagement, endpoint, type, and tool';
