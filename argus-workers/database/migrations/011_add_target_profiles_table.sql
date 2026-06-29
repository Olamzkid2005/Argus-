-- Migration 011: Create target_profiles table
-- Referenced by TargetProfileRepository but the original migration used a generic
-- profile_data JSONB column that doesn't match the repository's per-column INSERT.
--
-- Requirements: Store target profiles per org for scan configuration reuse
--
-- See autonomous-red-team-readiness-review.md Part 4 §2 — schema/runtime mismatch.

BEGIN;

CREATE TABLE IF NOT EXISTS target_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    target_domain TEXT NOT NULL,
    known_endpoints JSONB DEFAULT '[]'::jsonb,
    known_tech_stack JSONB DEFAULT '[]'::jsonb,
    confirmed_finding_types JSONB DEFAULT '[]'::jsonb,
    high_value_endpoints JSONB DEFAULT '[]'::jsonb,
    best_tools JSONB DEFAULT '[]'::jsonb,
    noisy_tools JSONB DEFAULT '[]'::jsonb,
    total_scans INTEGER NOT NULL DEFAULT 0,
    last_scan_at TIMESTAMPTZ,
    last_findings_count INTEGER DEFAULT 0,
    scan_ids JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, target_domain)
);

CREATE INDEX IF NOT EXISTS idx_target_profiles_org ON target_profiles(org_id);

COMMIT;
