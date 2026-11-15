-- Migration 032: Track missing runtime logging and scheduling tables.
--
-- tasks/scheduled.py reads and updates scheduled_engagements, and
-- tracing.StructuredLogger inserts into execution_logs, but neither table was
-- tracked by migrations. runtime/migration.ensure_tables() also creates
-- agent_decision_log and agent_state_log outside the migration ledger.
-- Tracking all five tables here keeps fresh databases, runtime bootstrapping,
-- and the migration ledger on the same DDL.
--
-- execution_spans is preserved for compatibility/history. Active spans are
-- exported through OpenTelemetry rather than written by the application.

BEGIN;

CREATE TABLE IF NOT EXISTS scheduled_engagements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID,
    target_url TEXT NOT NULL,
    authorized_scope JSONB NOT NULL DEFAULT '[]'::jsonb,
    scan_type TEXT NOT NULL DEFAULT 'url',
    aggressiveness TEXT NOT NULL DEFAULT 'default',
    agent_mode BOOLEAN NOT NULL DEFAULT FALSE,
    created_by TEXT,
    cron_expression TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_engagement_id UUID REFERENCES engagements(id) ON DELETE SET NULL,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scheduled_engagements_next_run
    ON scheduled_engagements(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS execution_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID,
    trace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_logs_engagement
    ON execution_logs(engagement_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_logs_trace
    ON execution_logs(trace_id);

CREATE TABLE IF NOT EXISTS execution_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID,
    trace_id TEXT NOT NULL,
    span_name TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_spans_engagement
    ON execution_spans(engagement_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_spans_trace
    ON execution_spans(trace_id);

CREATE TABLE IF NOT EXISTS agent_decision_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    action_id UUID NOT NULL,
    observation_hash TEXT NOT NULL,
    reasoning_hash TEXT NOT NULL,
    selected_tool TEXT NOT NULL,
    arguments JSONB,
    tool_cost_usd NUMERIC(10,4) DEFAULT 0,
    state_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_success BOOLEAN,
    execution_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_decision_log_engagement
    ON agent_decision_log(engagement_id);
CREATE INDEX IF NOT EXISTS idx_agent_decision_log_action
    ON agent_decision_log(action_id);

CREATE TABLE IF NOT EXISTS agent_state_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL UNIQUE REFERENCES engagements(id) ON DELETE CASCADE,
    state_version INTEGER NOT NULL DEFAULT 0,
    snapshot_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_state_log_eid
    ON agent_state_log(engagement_id);

-- Normalize the two agent tables on databases that were first bootstrapped by
-- runtime.ensure_tables() when uuid-ossp was available. gen_random_uuid() is
-- built into PostgreSQL and matches the rest of this migration history.
ALTER TABLE agent_decision_log
    ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE agent_state_log
    ALTER COLUMN id SET DEFAULT gen_random_uuid();

COMMIT;
