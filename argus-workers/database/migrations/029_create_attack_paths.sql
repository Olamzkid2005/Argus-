-- Migration 029: Create attack_paths table
--
-- AttackGraph persistence (attack_graph_db.py) and the snapshot/analysis and
-- post-exploitation readers all use attack_paths, but no schema or migration
-- created it. Snapshot creation therefore failed the analyze phase on a fresh
-- database with UndefinedTable.

CREATE TABLE IF NOT EXISTS attack_paths (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    path_nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    normalized_severity TEXT,
    chain_exploit_script TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attack_paths_engagement
    ON attack_paths(engagement_id, risk_score DESC);
