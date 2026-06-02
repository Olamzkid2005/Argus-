-- Migration 006: Add compliance reports table
-- Requirements: Step 17 - Compliance Reporting Framework

CREATE TABLE IF NOT EXISTS compliance_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    standard VARCHAR(50) NOT NULL CHECK (standard IN ('owasp_top10', 'pci_dss', 'soc2')),
    title VARCHAR(500) NOT NULL,
    report_data JSONB NOT NULL DEFAULT '{}',
    html_content TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'ready' CHECK (status IN ('generating', 'ready', 'failed')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index for engagement lookups
CREATE INDEX IF NOT EXISTS idx_compliance_reports_engagement
ON compliance_reports(engagement_id);

-- Index for standard type lookups
CREATE INDEX IF NOT EXISTS idx_compliance_reports_standard
ON compliance_reports(standard);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_compliance_reports_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_compliance_reports_updated_at ON compliance_reports;
CREATE TRIGGER trigger_compliance_reports_updated_at
    BEFORE UPDATE ON compliance_reports
    FOR EACH ROW
    EXECUTE FUNCTION update_compliance_reports_updated_at();

-- Comment documenting the table
COMMENT ON TABLE compliance_reports IS 'Stores generated compliance reports (OWASP Top 10, PCI DSS, SOC 2) for engagements.';
COMMENT ON COLUMN compliance_reports.report_data IS 'JSON report data including findings, summary, and metadata.';
COMMENT ON COLUMN compliance_reports.html_content IS 'Pre-rendered HTML report content for quick serving.';
