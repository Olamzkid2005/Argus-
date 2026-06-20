-- Migration 002: Audit Logging
-- Up: Creates audit log and performance log tables

BEGIN;

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_engagement ON audit_log(engagement_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);

CREATE TABLE IF NOT EXISTS performance_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    query TEXT,
    context JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_performance_log_operation ON performance_log(operation);
CREATE INDEX IF NOT EXISTS idx_performance_log_duration ON performance_log(duration_ms);

COMMIT;

-- Down:
-- BEGIN;
-- DROP TABLE IF EXISTS performance_log;
-- DROP TABLE IF EXISTS audit_log;
-- COMMIT;
