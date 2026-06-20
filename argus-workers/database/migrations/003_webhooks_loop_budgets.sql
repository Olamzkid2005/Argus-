-- Migration 003: Webhooks and Loop Budgets
-- Up: Creates tables for webhook dispatch and scan loop budget tracking

BEGIN;

-- Webhooks table for dispatching finding notifications
CREATE TABLE IF NOT EXISTS webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID REFERENCES engagements(id) ON DELETE CASCADE,
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    webhook_url TEXT NOT NULL,
    events JSONB DEFAULT '["finding_discovered"]',
    secret TEXT,
    last_triggered TIMESTAMPTZ,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_scheme CHECK (
        webhook_url ~ '^https?://' AND
        webhook_url !~ '^https?://(127\\.0\\.0\\.1|localhost|169\\.254\\.|10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.|0\\.0\\.0\\.0)'
    )
);

CREATE INDEX IF NOT EXISTS idx_webhooks_engagement ON webhooks(engagement_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_org ON webhooks(org_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_enabled ON webhooks(enabled);

-- Loop budgets table for tracking scan iteration budgets
CREATE TABLE IF NOT EXISTS loop_budgets (
    engagement_id UUID PRIMARY KEY REFERENCES engagements(id) ON DELETE CASCADE,
    max_cycles INTEGER NOT NULL DEFAULT 5,
    max_depth INTEGER NOT NULL DEFAULT 3,
    max_llm_reviews INTEGER NOT NULL DEFAULT 50,
    current_cycles INTEGER NOT NULL DEFAULT 0,
    current_depth INTEGER NOT NULL DEFAULT 0,
    current_llm_reviews INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;

-- Down:
-- BEGIN;
-- DROP TABLE IF EXISTS loop_budgets;
-- DROP TABLE IF EXISTS webhooks;
-- COMMIT;
