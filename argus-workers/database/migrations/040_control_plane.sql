-- Migration 040: fact-and-intent control plane (bootstrap / reason / explore)
--
-- Durable protocol state for the single dispatcher: worker registry, leader and
-- task-type leases, task records with fencing tokens, reason checkpoints and
-- the reserved bootstrap intent. Workers never read or write these tables; the
-- dispatcher owns every transition.
--
-- NOTE: no explicit BEGIN/COMMIT; the migration runner owns the transaction.

CREATE TABLE IF NOT EXISTS control_plane_workers (
    worker_id TEXT PRIMARY KEY,
    task_types TEXT[] NOT NULL DEFAULT '{}'::text[],
    max_running INTEGER NOT NULL DEFAULT 1,
    running INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    healthy BOOLEAN NOT NULL DEFAULT TRUE,
    unavailable_until TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE control_plane_workers IS
    'Worker capacity registry for the fact-and-intent dispatcher.';

CREATE TABLE IF NOT EXISTS control_plane_leases (
    engagement_id UUID NOT NULL,
    lease_type TEXT NOT NULL,
    owner TEXT NOT NULL,
    token UUID NOT NULL DEFAULT gen_random_uuid(),
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (engagement_id, lease_type),
    CONSTRAINT control_plane_leases_type CHECK (
        lease_type IN ('dispatcher', 'reason', 'bootstrap')
    )
);

COMMENT ON TABLE control_plane_leases IS
    'Single-owner dispatcher, reason and bootstrap leases with a fencing token.';

CREATE TABLE IF NOT EXISTS control_plane_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL,
    task_type TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    intent_node_id UUID,
    status TEXT NOT NULL DEFAULT 'running',
    lease_token UUID,
    request JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    conclusion_written BOOLEAN NOT NULL DEFAULT FALSE,
    attempt INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deadline_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT control_plane_tasks_type CHECK (
        task_type IN ('bootstrap', 'bootstrap_conclude', 'reason',
                      'explore', 'explore_conclude')
    ),
    CONSTRAINT control_plane_tasks_status CHECK (
        status IN ('running', 'succeeded', 'failed', 'cancelled', 'rejected', 'timed_out')
    )
);

CREATE INDEX IF NOT EXISTS idx_control_plane_tasks_engagement
    ON control_plane_tasks(engagement_id, status);
CREATE INDEX IF NOT EXISTS idx_control_plane_tasks_worker
    ON control_plane_tasks(worker_id, status);

CREATE TABLE IF NOT EXISTS control_plane_reason_checkpoints (
    engagement_id UUID PRIMARY KEY,
    fact_count INTEGER NOT NULL,
    hint_count INTEGER NOT NULL,
    open_intent_count INTEGER NOT NULL,
    last_outcome TEXT NOT NULL DEFAULT 'unknown',
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_plane_bootstrap (
    engagement_id UUID PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'reserved',
    goal_node_id UUID,
    origin_node_id UUID,
    reserved_intent_node_id UUID,
    attempt INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT control_plane_bootstrap_status CHECK (
        status IN ('reserved', 'completed', 'concluded', 'released')
    )
);
