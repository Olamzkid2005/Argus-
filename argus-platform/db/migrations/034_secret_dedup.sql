-- Migration 015: Add last_seen_at for secret finding deduplication.
--
-- Tracks when a secret was last detected across repeated scans.
-- The unique constraint on (engagement_id, type, endpoint) prevents
-- unbounded duplication of gitleaks/trufflehog/secret-scan findings.
BEGIN;

ALTER TABLE findings
ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Index for efficient dedup lookups by secret fingerprint
CREATE INDEX IF NOT EXISTS idx_findings_secret_dedup
    ON findings(engagement_id, type, endpoint)
    WHERE source_tool IN ('gitleaks', 'trufflehog', 'secret-scan');

COMMIT;
