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
COMMENT ON COLUMN graph_anchors.role IS 'Anchoring role, e.g. investigated, describes, affects.';

CREATE INDEX IF NOT EXISTS idx_graph_anchors_node ON graph_anchors(node_id);
CREATE INDEX IF NOT EXISTS idx_graph_anchors_asset ON graph_anchors(asset_id);

COMMIT;
