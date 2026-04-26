-- Add pagination helper view for engagements
CREATE OR REPLACE VIEW engagement_list AS
SELECT 
    e.id,
    e.target_url,
    e.status,
    e.scan_type,
    e.created_at,
    e.updated_at,
    e.completed_at,
    o.name as org_name,
    u.email as created_by_email,
    lb.max_cycles,
    (SELECT COUNT(*)::int FROM findings f WHERE f.engagement_id = e.id) as findings_count,
    (SELECT COUNT(*)::int FROM findings f WHERE f.engagement_id = e.id AND f.severity = 'CRITICAL') as critical_count
FROM engagements e
LEFT JOIN organizations o ON e.org_id = o.id
LEFT JOIN users u ON e.created_by = u.id
LEFT JOIN loop_budgets lb ON e.id = lb.engagement_id;

-- Add index for engagement list pagination
CREATE INDEX IF NOT EXISTS idx_engagements_org_created 
ON engagements(org_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_findings_engagement_severity 
ON findings(engagement_id, severity);

-- Add partial index for verified findings
CREATE INDEX IF NOT EXISTS idx_findings_verified 
ON findings(engagement_id) WHERE verified = true;

-- Add composite index for polling
CREATE INDEX IF NOT EXISTS idx_execution_logs_trace_time 
ON execution_logs(trace_id, created_at DESC);

-- Add index for rate limiting
CREATE INDEX IF NOT EXISTS idx_rate_limit_events_domain_time 
ON rate_limit_events(domain, created_at DESC);

-- Composite index for engagement filtering by org + status
CREATE INDEX IF NOT EXISTS idx_engagements_org_status
ON engagements(org_id, status, created_at DESC);

-- Composite index for findings filtering
CREATE INDEX IF NOT EXISTS idx_findings_engagement_created
ON findings(engagement_id, created_at DESC);

-- Composite index for tool metrics
CREATE INDEX IF NOT EXISTS idx_tool_metrics_tool_time
ON tool_metrics(tool_name, created_at DESC);

-- Partial index for active jobs
CREATE INDEX IF NOT EXISTS idx_job_states_active
ON job_states(engagement_id, created_at DESC) WHERE status = 'processing';

-- Analyze tables for query optimization
ANALYZE engagements;
ANALYZE findings;
ANALYZE execution_logs;