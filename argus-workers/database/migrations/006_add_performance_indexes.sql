-- Migration 006: Add performance indexes for common queries
-- Optimizes frequently accessed query patterns identified in production

-- ============================================================================
-- ENGAGEMENT QUERY OPTIMIZATION
-- ============================================================================

-- Composite index for org + status + created_at (dashboard filtering)
CREATE INDEX IF NOT EXISTS idx_engagements_org_status_created 
ON engagements(org_id, status, created_at DESC);

-- Partial index for active engagements (excludes complete/failed)
CREATE INDEX IF NOT EXISTS idx_engagements_active 
ON engagements(org_id, created_at DESC) 
WHERE status NOT IN ('complete', 'failed');

-- Index for target URL search (case-insensitive lookups)
CREATE INDEX IF NOT EXISTS idx_engagements_target_url 
ON engagements(target_url);

-- Index for completion tracking
CREATE INDEX IF NOT EXISTS idx_engagements_completed_at 
ON engagements(completed_at) 
WHERE completed_at IS NOT NULL;

-- ============================================================================
-- FINDINGS QUERY OPTIMIZATION
-- ============================================================================

-- Composite index for engagement + severity + confidence (dashboard stats)
CREATE INDEX IF NOT EXISTS idx_findings_engagement_severity_confidence 
ON findings(engagement_id, severity, confidence DESC);

-- Partial index for unverified findings (review queue)
CREATE INDEX IF NOT EXISTS idx_findings_unverified 
ON findings(engagement_id, created_at DESC) 
WHERE verified = false;

-- Index for endpoint analysis
CREATE INDEX IF NOT EXISTS idx_findings_endpoint 
ON findings(endpoint);

-- Index for source tool analytics
CREATE INDEX IF NOT EXISTS idx_findings_tool_created 
ON findings(source_tool, created_at DESC);

-- ============================================================================
-- JOIN QUERY OPTIMIZATION
-- ============================================================================

-- Foreign key index optimizations for common JOINs
CREATE INDEX IF NOT EXISTS idx_findings_engagement_id_type 
ON findings(engagement_id, type);

-- Covering index for engagement list query (avoids table lookups)
CREATE INDEX IF NOT EXISTS idx_engagements_covering 
ON engagements(org_id, status, created_at DESC, target_url, scan_type);

-- Covering index for findings list with severity filter
CREATE INDEX IF NOT EXISTS idx_findings_covering 
ON findings(engagement_id, severity, confidence, endpoint, source_tool, created_at);

-- ============================================================================
-- STATE AND JOB OPTIMIZATION
-- ============================================================================

-- Composite index for job state lookups by engagement
CREATE INDEX IF NOT EXISTS idx_job_states_engagement_type 
ON job_states(engagement_id, job_type, status);

-- Index for recent state transitions
CREATE INDEX IF NOT EXISTS idx_engagement_states_engagement_created 
ON engagement_states(engagement_id, created_at DESC);

-- ============================================================================
-- AUDIT AND LOGGING OPTIMIZATION
-- ============================================================================

-- Composite index for audit log queries
CREATE INDEX IF NOT EXISTS idx_audit_logs_org_action_created 
ON audit_logs(org_id, action, created_at DESC);

-- Index for execution log lookups
CREATE INDEX IF NOT EXISTS idx_execution_logs_engagement_event 
ON execution_logs(engagement_id, event_type, created_at DESC);

-- Index for trace_id lookups on execution logs and spans
CREATE INDEX IF NOT EXISTS idx_execution_logs_trace_id 
ON execution_logs(trace_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_execution_spans_trace_id 
ON execution_spans(trace_id, created_at ASC);

-- ============================================================================
-- BRIN INDEXES FOR TIME-SERIES DATA (large tables)
-- ============================================================================

-- BRIN index for time-series data on very large tables
CREATE INDEX IF NOT EXISTS idx_findings_created_brin 
ON findings USING BRIN (created_at) 
WITH (pages_per_range = 128);

CREATE INDEX IF NOT EXISTS idx_execution_logs_created_brin 
ON execution_logs USING BRIN (created_at) 
WITH (pages_per_range = 128);

-- ============================================================================
-- FULL-TEXT SEARCH INDEXES
-- ============================================================================

-- GIN index for JSONB evidence search
CREATE INDEX IF NOT EXISTS idx_findings_evidence_gin 
ON findings USING GIN (evidence);

-- GIN index for authorized scope search
CREATE INDEX IF NOT EXISTS idx_engagements_scope_gin 
ON engagements USING GIN (authorized_scope);

-- ============================================================================
-- ANALYZE TABLES
-- ============================================================================

ANALYZE engagements;
ANALYZE findings;
ANALYZE job_states;
ANALYZE execution_logs;
ANALYZE audit_logs;
