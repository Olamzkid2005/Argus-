-- Migration 036: Graph planner event loop (A3)
--
-- Adds the durable pieces the planner event loop needs:
--  - planner_turns: one row per debounced planning turn, so a burst of outbox
--    events is provably consumed by exactly one turn and turn bounds/errors are
--    recorded rather than held only in memory.
--  - graph_outbox.planner_turn_id: links consumed events to the turn that
--    coalesced them, so no wake is silently dropped.
--  - claim fencing + heartbeat columns on planner_todos: a claim carries a
--    random token and an expiry lease, and only the current token may heartbeat,
--    complete or release it.
--
-- NOTE: no explicit BEGIN/COMMIT; the migration runner owns the transaction.

CREATE TABLE IF NOT EXISTS planner_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'outbox',
    status TEXT NOT NULL DEFAULT 'running',
    events_consumed INTEGER NOT NULL DEFAULT 0,
    proposals_received INTEGER NOT NULL DEFAULT 0,
    intents_created INTEGER NOT NULL DEFAULT 0,
    duplicates_suppressed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

COMMENT ON TABLE planner_turns IS 'Durable graph planning turns; coalesced outbox bursts and their outcome.';
COMMENT ON COLUMN planner_turns.status IS 'Turn lifecycle: running, completed, failed.';

CREATE INDEX IF NOT EXISTS idx_planner_turns_engagement
    ON planner_turns(engagement_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_planner_turns_status
    ON planner_turns(engagement_id, status);

ALTER TABLE graph_outbox
    ADD COLUMN IF NOT EXISTS planner_turn_id UUID
        REFERENCES planner_turns(id) ON DELETE SET NULL;

COMMENT ON COLUMN graph_outbox.planner_turn_id IS
    'Planning turn that consumed this event; null while queued.';

ALTER TABLE planner_todos
    ADD COLUMN IF NOT EXISTS claim_token UUID,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN planner_todos.claim_token IS
    'Fencing token of the current claim; stale workers present a token that no longer matches.';
COMMENT ON COLUMN planner_todos.lease_expires_at IS
    'Database-clock lease expiry; an expired claim is reclaimable by another worker.';
COMMENT ON COLUMN planner_todos.last_heartbeat_at IS
    'Last accepted heartbeat for the current claim.';

CREATE UNIQUE INDEX IF NOT EXISTS idx_planner_todos_claim_token
    ON planner_todos(claim_token)
    WHERE claim_token IS NOT NULL;
