-- Migration 028: Create engagement_states history table
--
-- The state machine and scheduled scans insert into engagement_states on every
-- transition, and maintenance/audit queries read it back, but no schema or
-- migration ever created the table (006_add_performance_indexes.sql explicitly
-- notes it was missing). A fresh database therefore failed on the first recon
-- transition with UndefinedTable.

CREATE TABLE IF NOT EXISTS engagement_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason TEXT,
    trace_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_engagement_states_engagement
    ON engagement_states(engagement_id, created_at);
