-- Migration 007: Add materialized views for complex aggregations
-- Reduces query time for dashboard and reporting queries

-- ============================================================================
-- ENGAGEMENT DASHBOARD SUMMARY (per organization)
-- ============================================================================

DROP MATERIALIZED VIEW IF EXISTS mv_org_dashboard;
CREATE MATERIALIZED VIEW mv_org_dashboard AS
SELECT 
    e.org_id,
    COUNT(DISTINCT e.id) as total_engagements,
    COUNT(DISTINCT e.id) FILTER (WHERE e.status = 'complete') as completed_engagements,
    COUNT(DISTINCT e.id) FILTER (WHERE e.status = 'failed') as failed_engagements,
    COUNT(DISTINCT e.id) FILTER (WHERE e.status IN ('scanning', 'analyzing', 'recon')) as active_engagements,
    COUNT(f.id) as total_findings,
    COUNT(f.id) FILTER (WHERE f.severity = 'CRITICAL') as critical_findings,
    COUNT(f.id) FILTER (WHERE f.severity = 'HIGH') as high_findings,
    COUNT(f.id) FILTER (WHERE f.severity = 'MEDIUM') as medium_findings,
    COUNT(f.id) FILTER (WHERE f.verified = true) as verified_findings,
    AVG(f.confidence) as avg_confidence,
    MAX(e.created_at) as latest_engagement,
    MAX(f.created_at) as latest_finding
FROM engagements e
LEFT JOIN findings f ON e.id = f.engagement_id
GROUP BY e.org_id;

-- Unique index for concurrent refresh
CREATE UNIQUE INDEX idx_mv_org_dashboard_org 
ON mv_org_dashboard(org_id);

-- ============================================================================
-- ENGAGEMENT FINDINGS SUMMARY (per engagement)
-- ============================================================================

DROP MATERIALIZED VIEW IF EXISTS mv_engagement_findings;
CREATE MATERIALIZED VIEW mv_engagement_findings AS
SELECT 
    e.id as engagement_id,
    e.org_id,
    e.target_url,
    e.status,
    COUNT(f.id) as total_findings,
    COUNT(f.id) FILTER (WHERE f.severity = 'CRITICAL') as critical_count,
    COUNT(f.id) FILTER (WHERE f.severity = 'HIGH') as high_count,
    COUNT(f.id) FILTER (WHERE f.severity = 'MEDIUM') as medium_count,
    COUNT(f.id) FILTER (WHERE f.severity = 'LOW') as low_count,
    COUNT(f.id) FILTER (WHERE f.severity = 'INFO') as info_count,
    COUNT(f.id) FILTER (WHERE f.verified = true) as verified_count,
    AVG(f.confidence) as avg_confidence,
    MAX(f.created_at) as latest_finding,
    e.created_at,
    e.completed_at
FROM engagements e
LEFT JOIN findings f ON e.id = f.engagement_id
GROUP BY e.id, e.org_id, e.target_url, e.status, e.created_at, e.completed_at;

CREATE UNIQUE INDEX idx_mv_engagement_findings_id 
ON mv_engagement_findings(engagement_id);

CREATE INDEX idx_mv_engagement_findings_org 
ON mv_engagement_findings(org_id);

-- ============================================================================
-- TOOL PERFORMANCE METRICS
-- ============================================================================

DROP MATERIALIZED VIEW IF EXISTS mv_tool_performance;
CREATE MATERIALIZED VIEW mv_tool_performance AS
SELECT 
    tool_name,
    COUNT(*) as total_runs,
    COUNT(*) FILTER (WHERE success = true) as success_count,
    COUNT(*) FILTER (WHERE success = false) as failure_count,
    AVG(duration_ms) as avg_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_duration_ms,
    MAX(duration_ms) as max_duration_ms,
    MIN(duration_ms) as min_duration_ms,
    MAX(created_at) as latest_run
FROM tool_metrics
GROUP BY tool_name;

CREATE UNIQUE INDEX idx_mv_tool_performance_name 
ON mv_tool_performance(tool_name);

-- ============================================================================
-- REFRESH FUNCTIONS AND TRIGGERS
-- ============================================================================

-- Refresh function for org dashboard
CREATE OR REPLACE FUNCTION refresh_mv_org_dashboard()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_org_dashboard;
END;
$$ LANGUAGE plpgsql;

-- Refresh function for engagement findings
CREATE OR REPLACE FUNCTION refresh_mv_engagement_findings()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_engagement_findings;
END;
$$ LANGUAGE plpgsql;

-- Refresh function for tool performance
CREATE OR REPLACE FUNCTION refresh_mv_tool_performance()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_tool_performance;
END;
$$ LANGUAGE plpgsql;

-- Trigger function to refresh views on findings changes
CREATE OR REPLACE FUNCTION trigger_refresh_findings_views()
RETURNS TRIGGER AS $$
BEGIN
    -- Use pg_background or similar for async refresh in production
    -- For now, schedule refresh via Celery beat
    PERFORM pg_notify('refresh_views', 'findings');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create triggers for view refresh
DROP TRIGGER IF EXISTS refresh_findings_views ON findings;
CREATE TRIGGER refresh_findings_views
AFTER INSERT OR UPDATE OR DELETE ON findings
FOR EACH STATEMENT EXECUTE FUNCTION trigger_refresh_findings_views();

-- ============================================================================
-- QUERY PERFORMANCE LOGGING TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS query_performance_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_hash VARCHAR(64) NOT NULL,
    query_text TEXT,
    execution_time_ms INTEGER NOT NULL,
    rows_returned INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_query_perf_hash ON query_performance_log(query_hash);
CREATE INDEX idx_query_perf_created ON query_performance_log(created_at DESC);
