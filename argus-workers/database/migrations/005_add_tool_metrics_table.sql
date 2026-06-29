-- Migration 005: Create tool_metrics table
-- This must run before migration 010 which ALTERs tool_metrics to add engagement_id.
-- Requirements: Dashboard tool performance metrics
--
-- NOTE: The table uses `success` (BOOLEAN) rather than `status` (TEXT) to match
-- the ToolMetricsRepository.record_metric() INSERT and ToolHealthTracker queries
-- which SUM(CASE WHEN success THEN 1 ELSE 0 END).
-- See autonomous-red-team-readiness-review.md Part 3 §3.

BEGIN;

CREATE TABLE IF NOT EXISTS tool_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_name TEXT NOT NULL,
    engagement_id UUID REFERENCES engagements(id) ON DELETE SET NULL,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    duration_ms INTEGER,
    target_url TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_metrics_tool_name ON tool_metrics(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_metrics_engagement ON tool_metrics(engagement_id);

COMMIT;
