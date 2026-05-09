-- Step 1: Self-Calibrating Confidence — tool_accuracy table
-- Per-org, per-tool false-positive rate tracking with Bayesian prior
-- Migration: 035

CREATE TABLE tool_accuracy (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_tool     VARCHAR(100) NOT NULL,
    total_verdicts  INTEGER NOT NULL DEFAULT 0,
    true_positives  INTEGER NOT NULL DEFAULT 0,
    false_positives INTEGER NOT NULL DEFAULT 0,
    -- Running weighted rate: (fp + 0.5) / (total + 1)
    -- Bayesian prior avoids 0.0 or 1.0 when data is sparse
    fp_rate         DECIMAL(4,3) NOT NULL DEFAULT 0.200,
    last_updated    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (org_id, source_tool)
);

-- Pre-seed with neutral defaults for all known tools
-- fp_rate 0.2 = same as current hardcoded default — zero regression
INSERT INTO tool_accuracy (org_id, source_tool, fp_rate)
SELECT DISTINCT o.id, t.tool, 0.200
FROM organizations o
CROSS JOIN (VALUES
    ('nuclei'), ('nikto'), ('dalfox'), ('sqlmap'), ('arjun'),
    ('whatweb'), ('httpx'), ('katana'), ('naabu'), ('gau'),
    ('web_scanner'), ('jwt_tool'), ('commix'), ('testssl'),
    ('semgrep'), ('bandit'), ('gitleaks'), ('trivy'),
    ('browser_scanner'), ('subfinder'), ('amass'), ('ffuf')
) t(tool);

CREATE INDEX idx_tool_accuracy_org_tool ON tool_accuracy(org_id, source_tool);
