-- Migration 011: Create target_profiles table
-- Referenced by TargetProfileRepository but was never created in any migration.
-- Requirements: Store target profiles per org for scan configuration reuse

BEGIN;

CREATE TABLE IF NOT EXISTS target_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    target_domain TEXT NOT NULL,
    profile_data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, target_domain)
);

CREATE INDEX IF NOT EXISTS idx_target_profiles_org ON target_profiles(org_id);

COMMIT;
