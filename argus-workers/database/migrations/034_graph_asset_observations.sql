-- Migration 034: Graph A2 — asset observations, scoped identity and parent links
--
-- Scope: graph ingestion and coverage for the canonical asset graph.
--
-- Changes:
--  1. graph_assets gains parent links so a parent chain survives canonicalization
--     (A-01). parent_asset_id is self-referencing; deleting a parent detaches its
--     children instead of deleting them.
--  2. Asset identity becomes scope-aware. Migration 033 made (canonical_key,
--     asset_type) globally unique, which merged the same domain discovered under
--     two different tenant/workspace scopes into one row (A-03). Identity is now
--     unique per scope, with unscoped assets forming one shared bucket.
--  3. graph_asset_observations stores raw observations with their source tool,
--     parser version and confidence. Accepted observations point at the canonical
--     asset; rejected (out-of-scope) observations are retained for audit only and
--     must never become schedulable assets.
--
-- NOTE: no explicit BEGIN/COMMIT. The migration runner wraps each file in its own
-- transaction; an embedded COMMIT would let a later failing statement leave a
-- half-applied migration behind.

ALTER TABLE graph_assets
    ADD COLUMN IF NOT EXISTS parent_asset_id UUID REFERENCES graph_assets(id) ON DELETE SET NULL;
ALTER TABLE graph_assets
    ADD COLUMN IF NOT EXISTS parent_relationship TEXT;

COMMENT ON COLUMN graph_assets.parent_asset_id IS
    'Parent asset in the canonical hierarchy (root_domain -> subdomain -> ip/service/app/endpoint).';
COMMENT ON COLUMN graph_assets.parent_relationship IS
    'Relationship to the parent asset, e.g. child_of.';

-- Replace the global identity constraint with a scope-aware unique index. The
-- COALESCE sentinel keeps unscoped assets deduplicated (a plain used as a
-- bucket for the shared/global scope.
ALTER TABLE graph_assets DROP CONSTRAINT IF EXISTS graph_assets_unique_identity;

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_assets_scoped_identity
    ON graph_assets (
        COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid),
        canonical_key,
        asset_type
    );

COMMENT ON INDEX idx_graph_assets_scoped_identity IS
    'One canonical asset per (scope, canonical_key, asset_type); unscoped assets share one bucket.';

CREATE INDEX IF NOT EXISTS idx_graph_assets_parent ON graph_assets(parent_asset_id);

CREATE TABLE IF NOT EXISTS graph_asset_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID REFERENCES graph_assets(id) ON DELETE CASCADE,
    scope_id UUID,
    asset_type TEXT NOT NULL,
    observed_value TEXT NOT NULL,
    source TEXT NOT NULL,
    parser_version TEXT,
    confidence DOUBLE PRECISION,
    accepted BOOLEAN NOT NULL DEFAULT TRUE,
    rejection_reason TEXT,
    observation_count INTEGER NOT NULL DEFAULT 1,
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT graph_asset_observations_rejection_reason
        CHECK (accepted OR rejection_reason IS NOT NULL)
);

COMMENT ON TABLE graph_asset_observations IS
    'Raw asset observations from tools/actions, merged onto canonical graph_assets.';
COMMENT ON COLUMN graph_asset_observations.observed_value IS
    'Value as observed by the tool; the canonical key lives on graph_assets.';
COMMENT ON COLUMN graph_asset_observations.accepted IS
    'False for out-of-scope observations: retained for audit, never schedulable.';
COMMENT ON COLUMN graph_asset_observations.rejection_reason IS
    'Why the observation was rejected, e.g. out_of_scope.';

-- Replaying the same observation (same scope/type/value/source) increments the
-- count instead of creating a duplicate row (A-16).
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_asset_observations_identity
    ON graph_asset_observations (
        COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid),
        asset_type,
        observed_value,
        source
    );

CREATE INDEX IF NOT EXISTS idx_graph_asset_observations_asset
    ON graph_asset_observations(asset_id);
CREATE INDEX IF NOT EXISTS idx_graph_asset_observations_scope
    ON graph_asset_observations(scope_id, asset_type);
CREATE INDEX IF NOT EXISTS idx_graph_asset_observations_accepted
    ON graph_asset_observations(accepted);
