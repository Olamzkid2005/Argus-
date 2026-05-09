-- Step 4: Target Memory — target_profiles table
-- Per-domain intelligence profiles for cross-scan learning
-- Migration: 036

CREATE TABLE target_profiles (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id                  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    target_domain           VARCHAR(512) NOT NULL,
    -- Surface knowledge (bounded arrays to keep prompt size predictable)
    known_endpoints         JSONB NOT NULL DEFAULT '[]',     -- max 100
    known_tech_stack        JSONB NOT NULL DEFAULT '[]',     -- stable fingerprint
    known_open_ports        JSONB NOT NULL DEFAULT '[]',     -- max 50
    known_subdomains        JSONB NOT NULL DEFAULT '[]',     -- max 50
    -- Finding knowledge (what actually worked)
    confirmed_finding_types JSONB DEFAULT '[]',  -- types confirmed as TP in past scans
    false_positive_types    JSONB DEFAULT '[]',  -- types always FP here
    high_value_endpoints    JSONB DEFAULT '[]',  -- endpoints with confirmed findings
    -- Tool performance (feeds agent prompt)
    best_tools              JSONB DEFAULT '[]',  -- [{tool, finding_count, last_seen}]
    noisy_tools             JSONB DEFAULT '[]',  -- tools >50% FP on this target
    -- Scan history (for diff engine)
    total_scans             INTEGER NOT NULL DEFAULT 0,
    last_scan_at            TIMESTAMP WITH TIME ZONE,
    last_findings_count     INTEGER DEFAULT 0,
    scan_ids                JSONB DEFAULT '[]',  -- engagement IDs, newest first, max 20
    -- Regression tracking
    fixed_finding_fingerprints JSONB DEFAULT '[]',  -- fingerprints of findings marked fixed
    regressed_findings         JSONB DEFAULT '[]',  -- fingerprints that came back
    -- Last diff summary (for monitoring dashboard)
    last_diff_summary       JSONB DEFAULT NULL,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (org_id, target_domain)
);

CREATE INDEX idx_target_profiles_domain ON target_profiles(org_id, target_domain);
