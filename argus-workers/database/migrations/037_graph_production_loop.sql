-- Migration 037: Graph production loop, worker protocol and audit trail
--
-- Adds the durable pieces that turn the graph planner from a testable library
-- into a running loop and close the remaining A-/C- conformance surfaces:
--  - graph_actions: idempotent action/result ledger keyed by
--    (engagement_id, action_id), so a re-delivered result is one logical write.
--  - graph_traces: redacted, engagement-scoped worker trace summaries that
--    another worker can reuse without repeating the action (A-13).
--  - graph_write_rejections: audit record for rejected edges/anchors/proposals
--    (A-05), written outside the failed mutation's transaction.
--
-- NOTE: no explicit BEGIN/COMMIT; the migration runner owns the transaction.

CREATE TABLE IF NOT EXISTS graph_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL,
    action_id TEXT NOT NULL,
    intent_node_id UUID,
    worker_id TEXT,
    tool TEXT,
    canonical_arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome TEXT NOT NULL DEFAULT 'completed',
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT graph_actions_unique_action UNIQUE (engagement_id, action_id)
);

COMMENT ON TABLE graph_actions IS
    'Idempotent graph action/result ledger; replaying an action_id returns the recorded result.';

CREATE INDEX IF NOT EXISTS idx_graph_actions_engagement
    ON graph_actions(engagement_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_graph_actions_intent
    ON graph_actions(intent_node_id);

CREATE TABLE IF NOT EXISTS graph_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL,
    intent_node_id UUID,
    worker_id TEXT,
    tool TEXT,
    summary TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE graph_traces IS
    'Redacted engagement-scoped worker trace summaries for cross-worker reuse (A-13).';

CREATE INDEX IF NOT EXISTS idx_graph_traces_engagement
    ON graph_traces(engagement_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_graph_traces_intent
    ON graph_traces(intent_node_id);

CREATE TABLE IF NOT EXISTS graph_write_rejections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID,
    operation TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE graph_write_rejections IS
    'Audit trail for graph writes rejected before mutation (A-05).';

CREATE INDEX IF NOT EXISTS idx_graph_write_rejections_engagement
    ON graph_write_rejections(engagement_id, created_at DESC);

-- Intent-node claims for MCP workers: one live intent per worker, with the
-- same fencing-token + lease semantics used by planner todos (A-11/A-12).
ALTER TABLE graph_nodes
    ADD COLUMN IF NOT EXISTS claim_token UUID,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;

COMMENT ON COLUMN graph_nodes.claim_token IS
    'Fencing token of the worker currently executing this intent node.';
COMMENT ON COLUMN graph_nodes.lease_expires_at IS
    'Database-clock expiry for a worker intent claim.';

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_nodes_claim_token
    ON graph_nodes(claim_token)
    WHERE claim_token IS NOT NULL;
