-- Migration 033: Argus graph tables (first implementation pass)
-- Scope: canonical asset identity + exploration nodes + anchors, minimal A-04 subset.
--
-- This is the canonical graph layer owned by the exploration/planning pipeline.
-- It is intentionally separate from the existing attack_graph tables so the
-- vulnerability chain/risk scoring model is not repurposed as the exploration graph.
--
-- Tables:
--  - graph_assets: canonical asset identity, deduplicated by canonical_key + asset_type.
--  - graph_nodes: per-engagement exploration nodes (goal/intent/fact/finding/hint).
--  - graph_anchors: explicit many-to-many links from a node to one or more assets.

BEGIN;

CREATE TABLE IF NOT EXISTS graph_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_id UUID,
    canonical_key TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    display_value TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT graph_assets_unique_identity UNIQUE (canonical_key, asset_type)
);

COMMENT ON TABLE graph_assets IS 'Argus canonical asset identity for the exploration pipeline.';
COMMENT ON COLUMN graph_assets.canonical_key IS 'Stable deduplication key for this asset identity.';
COMMENT ON COLUMN graph_assets.asset_type IS 'Canonical asset type, e.g. root_domain, subdomain, ip, service, app, endpoint.';
COMMENT ON COLUMN graph_assets.scope_id IS 'Owning scope boundary, when applicable.';

CREATE INDEX IF NOT EXISTS idx_graph_assets_scope ON graph_assets(scope_id);
CREATE INDEX IF NOT EXISTS idx_graph_assets_type ON graph_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_graph_assets_identity ON graph_assets(canonical_key, asset_type);

CREATE TABLE IF NOT EXISTS graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT NOT NULL DEFAULT 'open',
    priority INTEGER NOT NULL DEFAULT 0,
    origin TEXT,
    owner TEXT,
    source_task_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT graph_nodes_unique_node UNIQUE (engagement_id, kind, payload)
);

COMMENT ON TABLE graph_nodes IS 'Argus exploration graph nodes (goal/intent/fact/finding/hint).';
COMMENT ON COLUMN graph_nodes.kind IS 'One of goal, intent, fact, finding, hint.';
COMMENT ON COLUMN graph_nodes.state IS 'Node state, e.g. open, running, concluded, blocked, cancelled.';
COMMENT ON COLUMN graph_nodes.owner IS 'Current owner/worker id when the node is claimed.';

CREATE INDEX IF NOT EXISTS idx_graph_nodes_engagement ON graph_nodes(engagement_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_state ON graph_nodes(engagement_id, state);

CREATE TABLE IF NOT EXISTS graph_anchors (
    node_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES graph_assets(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'related',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (node_id, asset_id, role)
);

COMMENT ON TABLE graph_anchors IS 'Argus explicit anchors from exploration nodes to canonical assets.';
CREATE TABLE IF NOT EXISTS graph_node_edges (
    engagement_id UUID NOT NULL,
    source_node_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL DEFAULT 'related',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_node_id, target_node_id, edge_type)
);

CREATE TABLE IF NOT EXISTS graph_anchor_scopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    anchor_id UUID NOT NULL REFERENCES graph_anchors(node_id) ON DELETE CASCADE,
    scope_id UUID NOT NULL,
    incorporated_by UUID,
    coverage_state TEXT NOT NULL DEFAULT 'pending',
    incorporated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT graph_anchor_scopes_unique UNIQUE (anchor_id, scope_id)
);

CREATE TABLE IF NOT EXISTS planner_frontier (
    engagement_id UUID NOT NULL,
    node_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open',
    priority INTEGER NOT NULL DEFAULT 0,
    frontier_reason TEXT,
    incorporated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (engagement_id, node_id)
);

CREATE TABLE IF NOT EXISTS planner_todos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL,
    canonical_node_id UUID,
    exploration_node_id UUID,
    frontier_position JSONB,
    todo_type TEXT NOT NULL DEFAULT 'plan',
    status TEXT NOT NULL DEFAULT 'open',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    depends_on UUID,
    owner TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS graph_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_type TEXT NOT NULL DEFAULT 'graph',
    scope_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    cause_node_id UUID,
    cause_engagement_id UUID,
    status TEXT NOT NULL DEFAULT 'queued',
    dequeued_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE graph_node_edges IS 'Per-engagement exploration edges; traceable to canonical nodes.';
COMMENT ON COLUMN graph_node_edges.edge_type IS 'Typed relationship between exploration nodes.';

COMMENT ON TABLE graph_anchor_scopes IS 'Engagement-scoped anchors + coverage metadata on top of canonical anchors.';
COMMENT ON COLUMN graph_anchor_scopes.coverage_state IS 'How an engagement has incorporated a canonical anchor: pending, incorporated, covered, archived.';

COMMENT ON TABLE planner_frontier IS 'Recoverable planner frontier per engagement, derived from graph and todo state.';

COMMENT ON TABLE planner_todos IS 'Persistent planner todo store; durable representation of planner work.';
COMMENT ON COLUMN planner_todos.todo_type IS 'Kind of todo: plan, expand, verify, report, reconcile.';
COMMENT ON COLUMN planner_todos.status IS 'Todo lifecycle: open, in_progress, done, blocked.';

COMMENT ON TABLE graph_outbox IS 'Graph-side change outbox for downstream planning/exploration/reconciliation.';

CREATE INDEX IF NOT EXISTS idx_graph_node_edges_engagement ON graph_node_edges(engagement_id);
CREATE INDEX IF NOT EXISTS idx_graph_node_edges_source ON graph_node_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_node_edges_target ON graph_node_edges(target_node_id);

CREATE INDEX IF NOT EXISTS idx_graph_anchor_scopes_anchor ON graph_anchor_scopes(anchor_id);
CREATE INDEX IF NOT EXISTS idx_graph_anchor_scopes_scope ON graph_anchor_scopes(scope_id);

CREATE INDEX IF NOT EXISTS idx_planner_frontier_engagement ON planner_frontier(engagement_id);
CREATE INDEX IF NOT EXISTS idx_planner_frontier_state ON planner_frontier(engagement_id, state);

CREATE INDEX IF NOT EXISTS idx_planner_todos_engagement ON planner_todos(engagement_id);
CREATE INDEX IF NOT EXISTS idx_planner_todos_status ON planner_todos(engagement_id, status);
CREATE INDEX IF NOT EXISTS idx_planner_todos_depends ON planner_todos(depends_on);

CREATE INDEX IF NOT EXISTS idx_graph_outbox_status ON graph_outbox(status);
CREATE INDEX IF NOT EXISTS idx_graph_outbox_scope ON graph_outbox(scope_type, scope_id);

COMMIT;
