-- Migration 035: Graph tenant boundary on the canonical graph (A-03)
--
-- A scope (engagement) belongs to one tenant (engagements.org_id). Graph assets
-- and observations record that tenant so a write naming a different tenant than
-- the scope owner can be rejected instead of silently landing in the graph.
--
-- Identity stays (scope, canonical_key, asset_type); tenant_id is ownership
-- evidence used to enforce/verify the boundary, not part of the dedupe key.
--
-- NOTE: no explicit BEGIN/COMMIT. The migration runner wraps each file in its own
-- transaction.

ALTER TABLE graph_assets
    ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE graph_asset_observations
    ADD COLUMN IF NOT EXISTS tenant_id UUID;

COMMENT ON COLUMN graph_assets.tenant_id IS
    'Tenant that owns this asset; must match the owning engagement''s org_id.';
COMMENT ON COLUMN graph_asset_observations.tenant_id IS
    'Tenant of the write that produced this observation, for boundary audits.';

CREATE INDEX IF NOT EXISTS idx_graph_assets_tenant ON graph_assets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_graph_asset_observations_tenant
    ON graph_asset_observations(tenant_id);
