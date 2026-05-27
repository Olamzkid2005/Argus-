-- Migration 042: Compliance Scores (per-control tracking)
-- Tracks compliance posture at the individual control level per engagement.
-- Each row represents the status of a specific compliance control within a framework.
-- This enables "PCI DSS compliance dropped from 87% to 71% because 3 new HIGH
-- findings map to Requirement 6.3" — bridging raw findings to executive reporting.

CREATE TABLE IF NOT EXISTS compliance_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    framework VARCHAR(50) NOT NULL,  -- 'owasp_top10', 'pci_dss', 'soc2', 'nist_csf'
    control_id VARCHAR(100) NOT NULL,  -- e.g. 'A03:2021', '6.5.1', 'CC6.1', 'PR.AC-4'
    control_name VARCHAR(500) NOT NULL,  -- Human-readable control name
    status VARCHAR(20) NOT NULL DEFAULT 'not_tested',
        -- 'compliant' = no failing findings mapped here
        -- 'failing' = at least one active finding mapped here
        -- 'not_tested' = no engagement findings cover this control
    severity VARCHAR(50),  -- Worst severity among findings mapped to this control
    finding_count INTEGER NOT NULL DEFAULT 0,
    last_finding_at TIMESTAMP WITH TIME ZONE,
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_control_status CHECK (status IN ('compliant', 'failing', 'not_tested')),
    CONSTRAINT unique_org_framework_control UNIQUE (org_id, engagement_id, framework, control_id)
);

CREATE INDEX idx_compliance_scores_org ON compliance_scores(org_id);
CREATE INDEX idx_compliance_scores_engagement ON compliance_scores(engagement_id);
CREATE INDEX idx_compliance_scores_framework ON compliance_scores(framework);
CREATE INDEX idx_compliance_scores_status ON compliance_scores(status);
CREATE INDEX idx_compliance_scores_org_framework ON compliance_scores(org_id, framework);

COMMENT ON TABLE compliance_scores IS
'Per-control compliance tracking that updates after every scan.
Supports drill-down from "your PCI DSS score is 71%" to
"Requirement 6.3 is failing because of 3 SQL injection findings".';
