-- Migration 008: Multi-tenant resource isolation
-- Implements per-organization schema isolation, resource quotas, and tenant-aware pooling

-- ============================================================================
-- ORGANIZATION RESOURCE QUOTAS
-- ============================================================================

CREATE TABLE IF NOT EXISTS org_quotas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
    max_scans INTEGER NOT NULL DEFAULT 10,
    max_storage_mb INTEGER NOT NULL DEFAULT 1024,
    max_api_calls_per_hour INTEGER NOT NULL DEFAULT 1000,
    max_concurrent_scans INTEGER NOT NULL DEFAULT 2,
    max_users INTEGER NOT NULL DEFAULT 5,
    current_storage_mb INTEGER NOT NULL DEFAULT 0,
    current_api_calls_this_hour INTEGER NOT NULL DEFAULT 0,
    api_calls_window_start TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_org_quotas_org ON org_quotas(org_id);

-- ============================================================================
-- ORGANIZATION SCHEMA ISOLATION (row-level security approach)
-- ============================================================================

-- Enable row-level security on core tables
ALTER TABLE engagements ENABLE ROW LEVEL SECURITY;
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Create policy function that checks org access
CREATE OR REPLACE FUNCTION get_current_org_id()
RETURNS UUID AS $$
BEGIN
    RETURN current_setting('app.current_org_id', true)::UUID;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Engagement RLS policy
CREATE POLICY engagement_org_isolation ON engagements
    USING (org_id = get_current_org_id() OR get_current_org_id() IS NULL);

-- Findings RLS policy (via engagement)
CREATE POLICY findings_org_isolation ON findings
    USING (engagement_id IN (
        SELECT id FROM engagements 
        WHERE org_id = get_current_org_id() OR get_current_org_id() IS NULL
    ));

-- Audit logs RLS policy
CREATE POLICY audit_logs_org_isolation ON audit_logs
    USING (org_id = get_current_org_id() OR get_current_org_id() IS NULL);

-- ============================================================================
-- TENANT-AWARE CONNECTION POOLING HELPERS
-- ============================================================================

-- Function to set tenant context (called on every connection)
CREATE OR REPLACE FUNCTION set_tenant_context(p_org_id UUID)
RETURNS void AS $$
BEGIN
    PERFORM set_config('app.current_org_id', p_org_id::text, false);
END;
$$ LANGUAGE plpgsql;

-- Function to reset tenant context
CREATE OR REPLACE FUNCTION reset_tenant_context()
RETURNS void AS $$
BEGIN
    PERFORM set_config('app.current_org_id', '', false);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- ORGANIZATION RATE LIMITING
-- ============================================================================

CREATE TABLE IF NOT EXISTS org_rate_limits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    endpoint_pattern VARCHAR(255) NOT NULL, -- e.g., '/api/engagement/*'
    max_requests INTEGER NOT NULL DEFAULT 100,
    window_seconds INTEGER NOT NULL DEFAULT 60,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(org_id, endpoint_pattern)
);

CREATE INDEX idx_org_rate_limits_org ON org_rate_limits(org_id);

-- Function to check if org is within rate limit
CREATE OR REPLACE FUNCTION check_org_rate_limit(
    p_org_id UUID,
    p_endpoint VARCHAR(255)
)
RETURNS BOOLEAN AS $$
DECLARE
    v_limit INTEGER;
    v_window INTEGER;
    v_count INTEGER;
BEGIN
    SELECT max_requests, window_seconds
    INTO v_limit, v_window
    FROM org_rate_limits
    WHERE org_id = p_org_id
      AND p_endpoint LIKE endpoint_pattern;
    
    -- Default limit if no specific rule
    IF v_limit IS NULL THEN
        v_limit := 100;
        v_window := 60;
    END IF;
    
    -- Count recent API calls from audit log
    SELECT COUNT(*) INTO v_count
    FROM audit_logs
    WHERE org_id = p_org_id
      AND action LIKE 'api_%'
      AND created_at > CURRENT_TIMESTAMP - (v_window || ' seconds')::INTERVAL;
    
    RETURN v_count < v_limit;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- RESOURCE USAGE TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS org_resource_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    resource_type VARCHAR(50) NOT NULL, -- 'scan', 'storage', 'api_call'
    amount INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_org_resource_usage_org_type ON org_resource_usage(org_id, resource_type, created_at DESC);

-- Function to increment resource usage
CREATE OR REPLACE FUNCTION increment_resource_usage(
    p_org_id UUID,
    p_resource_type VARCHAR(50),
    p_amount INTEGER DEFAULT 1
)
RETURNS void AS $$
BEGIN
    INSERT INTO org_resource_usage (org_id, resource_type, amount)
    VALUES (p_org_id, p_resource_type, p_amount);
    
    -- Update quota current values
    IF p_resource_type = 'storage' THEN
        UPDATE org_quotas 
        SET current_storage_mb = current_storage_mb + p_amount,
            updated_at = CURRENT_TIMESTAMP
        WHERE org_id = p_org_id;
    ELSIF p_resource_type = 'api_call' THEN
        UPDATE org_quotas 
        SET current_api_calls_this_hour = current_api_calls_this_hour + p_amount,
            updated_at = CURRENT_TIMESTAMP
        WHERE org_id = p_org_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- DEFAULT QUOTAS FOR EXISTING ORGS
-- ============================================================================

INSERT INTO org_quotas (org_id, max_scans, max_storage_mb, max_api_calls_per_hour, max_concurrent_scans, max_users)
SELECT id, 10, 1024, 1000, 2, 5
FROM organizations
ON CONFLICT (org_id) DO NOTHING;
