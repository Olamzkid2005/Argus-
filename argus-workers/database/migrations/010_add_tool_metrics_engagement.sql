-- Migration 010: Add engagement_id to tool_metrics for org-scoped performance metrics
-- Requirements: Dashboard tool performance metrics should be org-specific

ALTER TABLE tool_metrics ADD COLUMN IF NOT EXISTS engagement_id UUID REFERENCES engagements(id) ON DELETE SET NULL;

-- Index for org-scoped queries joining through engagements
CREATE INDEX IF NOT EXISTS idx_tool_metrics_engagement
ON tool_metrics(engagement_id);

COMMENT ON COLUMN tool_metrics.engagement_id IS 'Links tool metrics to an engagement, enabling org-scoped performance queries via engagement.org_id JOIN.';
