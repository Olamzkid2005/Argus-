-- Migration 011: Add asset inventory table for tracking discovered/managed assets
-- Requirements: Asset Inventory page

CREATE TABLE IF NOT EXISTS assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    engagement_id UUID REFERENCES engagements(id) ON DELETE SET NULL,
    asset_type VARCHAR(100) NOT NULL,
    identifier VARCHAR(2048) NOT NULL,
    display_name VARCHAR(255),
    description TEXT,
    attributes JSONB NOT NULL DEFAULT '{}',
    risk_score DECIMAL(4, 2) DEFAULT 0.00,
    risk_level VARCHAR(50) DEFAULT 'LOW',
    criticality VARCHAR(50) DEFAULT 'medium',
    lifecycle_status VARCHAR(50) NOT NULL DEFAULT 'active',
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_scanned_at TIMESTAMP WITH TIME ZONE,
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_asset_type CHECK (asset_type IN ('domain', 'ip', 'endpoint', 'repository', 'container', 'api', 'network', 'cloud_resource')),
    CONSTRAINT valid_lifecycle_status CHECK (lifecycle_status IN ('active', 'inactive', 'decommissioned', 'unknown')),
    CONSTRAINT valid_risk_level CHECK (risk_level IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO')),
    CONSTRAINT valid_criticality CHECK (criticality IN ('critical', 'high', 'medium', 'low', 'informational')),
    CONSTRAINT unique_org_identifier_type UNIQUE (org_id, identifier, asset_type)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_assets_org_id ON assets(org_id);
CREATE INDEX IF NOT EXISTS idx_assets_engagement_id ON assets(engagement_id);
CREATE INDEX IF NOT EXISTS idx_assets_asset_type ON assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_risk_score ON assets(risk_score);
CREATE INDEX IF NOT EXISTS idx_assets_lifecycle_status ON assets(lifecycle_status);

COMMENT ON TABLE assets IS 'Asset inventory — discovered and manually added assets with risk scoring.';
COMMENT ON COLUMN assets.risk_level IS 'Calculated risk level based on exposure and vulnerability data.';
COMMENT ON COLUMN assets.attributes IS 'Flexible JSON metadata for asset-specific attributes.';
