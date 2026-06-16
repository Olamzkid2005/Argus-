-- Migration 016: Add finding feedback table for analyst feedback loop
CREATE TABLE IF NOT EXISTS finding_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id UUID NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    is_true_positive BOOLEAN NOT NULL,
    analyst_notes TEXT DEFAULT '',
    corrected_severity VARCHAR(10) DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (finding_id, engagement_id)
);

CREATE INDEX IF NOT EXISTS idx_finding_feedback_engagement
    ON finding_feedback(engagement_id);
CREATE INDEX IF NOT EXISTS idx_finding_feedback_tool
    ON finding_feedback(finding_id);
