-- Step 13: Live PoC Generator — add poc_generated column to findings
-- Migration: 037

ALTER TABLE findings ADD COLUMN poc_generated JSONB;
ALTER TABLE findings ADD COLUMN poc_generated_at TIMESTAMP WITH TIME ZONE;

-- Index for fetching findings that have PoC vs those that don't
CREATE INDEX idx_findings_has_poc ON findings((poc_generated IS NOT NULL));
