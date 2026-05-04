-- Migration 015: Add unique constraint for finding deduplication
-- Prevents duplicate findings from concurrent tools

ALTER TABLE findings
ADD CONSTRAINT uq_finding_dedup
UNIQUE (engagement_id, endpoint, type, source_tool);

COMMENT ON CONSTRAINT uq_finding_dedup ON findings IS
    'Prevents duplicate findings with the same engagement, endpoint, type, and tool';
