-- Migration 034: Compliance Posture Snapshots
-- Stores continuous compliance posture scores across regulatory frameworks
-- (OWASP Top 10, PCI DSS, SOC 2) for trend analysis.

CREATE TABLE IF NOT EXISTS compliance_posture_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    composite_score DECIMAL(5, 1) NOT NULL,  -- 0.0 - 100.0
    framework_scores JSONB NOT NULL DEFAULT '{}',  -- {owasp_top10: {score, total_findings, critical_count, ...}}
    total_findings INTEGER NOT NULL DEFAULT 0,
    trend VARCHAR(20) NOT NULL DEFAULT 'stable',  -- improving, declining, stable
    previous_score DECIMAL(5, 1),  -- Score from the snapshot before this one
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_trend CHECK (trend IN ('improving', 'declining', 'stable'))
);

CREATE INDEX idx_cps_engagement_id ON compliance_posture_snapshots(engagement_id);
CREATE INDEX idx_cps_computed_at ON compliance_posture_snapshots(computed_at DESC);
CREATE INDEX idx_cps_composite_score ON compliance_posture_snapshots(composite_score DESC);

-- Function to get latest posture for an engagement
CREATE OR REPLACE FUNCTION get_latest_posture(p_engagement_id UUID)
RETURNS TABLE (
    composite_score DECIMAL(5, 1),
    trend VARCHAR(20),
    total_findings INTEGER,
    computed_at TIMESTAMP WITH TIME ZONE
) LANGUAGE SQL STABLE AS $$
    SELECT composite_score, trend, total_findings, computed_at
    FROM compliance_posture_snapshots
    WHERE engagement_id = p_engagement_id
    ORDER BY computed_at DESC
    LIMIT 1;
$$;
