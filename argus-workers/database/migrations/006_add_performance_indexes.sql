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

-- NOTE: job_states and engagement_states tables not yet created —
-- indexes omitted until those tables exist.

-- ============================================================================
-- AUDIT AND LOGGING OPTIMIZATION
-- ============================================================================

-- Index for audit_log table (created in migration 002)
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type_created
ON audit_log(event_type, created_at DESC);

-- NOTE: execution_logs and execution_spans tables not yet created —
-- indexes omitted until those tables exist.

-- ============================================================================
-- BRIN INDEXES FOR TIME-SERIES DATA (large tables)
-- ============================================================================

-- BRIN index for time-series data on findings table
CREATE INDEX IF NOT EXISTS idx_findings_created_brin 
ON findings USING BRIN (created_at) 
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
ANALYZE audit_log;
