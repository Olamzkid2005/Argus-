-- Migration 032: Scheduled Engagements
-- Adds recurring scan scheduling via Celery Beat + cron expressions
--
-- Requirements: Users can set up weekly/daily/monthly automated scans
-- without manual triggering.

-- Scheduled engagements table
CREATE TABLE IF NOT EXISTS scheduled_engagements (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by      UUID NOT NULL REFERENCES users(id),
    target_url      VARCHAR(2048) NOT NULL,
    authorized_scope JSONB NOT NULL DEFAULT '{}',
    scan_type       VARCHAR(50) NOT NULL DEFAULT 'url',
    aggressiveness  VARCHAR(20) NOT NULL DEFAULT 'default',
    agent_mode      BOOLEAN NOT NULL DEFAULT TRUE,
    cron_expression VARCHAR(100) NOT NULL,  -- e.g. '0 2 * * 1' (Mon 2am)
    next_run_at     TIMESTAMP WITH TIME ZONE,
    last_run_at     TIMESTAMP WITH TIME ZONE,
    last_engagement_id UUID REFERENCES engagements(id) ON DELETE SET NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for the Celery Beat query: find enabled schedules due to run
CREATE INDEX IF NOT EXISTS idx_scheduled_next_run
    ON scheduled_engagements(next_run_at)
    WHERE enabled = TRUE;

-- Index for org-level listing
CREATE INDEX IF NOT EXISTS idx_scheduled_org
    ON scheduled_engagements(org_id);
