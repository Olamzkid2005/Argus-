BEGIN;

CREATE TABLE IF NOT EXISTS hypotheses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    root_cause_key TEXT,
    source_finding_id UUID,  -- populated for single-finding hypotheses; NULL for grouped
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (status IN ('UNVERIFIED', 'CONFIRMED', 'REJECTED')),
    verification_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    supporting_finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    refuting_finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    suggested_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Prevent duplicate generation on concurrent run_analysis() calls.
-- Grouped hypotheses dedup on (engagement_id, root_cause_key).
-- Single-finding hypotheses dedup on (engagement_id, source_finding_id).
CREATE UNIQUE INDEX IF NOT EXISTS idx_hypotheses_engagement_root_cause
    ON hypotheses(engagement_id, root_cause_key) WHERE root_cause_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_hypotheses_engagement_source_finding
    ON hypotheses(engagement_id, source_finding_id) WHERE source_finding_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_hypotheses_engagement_id ON hypotheses(engagement_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON hypotheses(status);

COMMIT;
