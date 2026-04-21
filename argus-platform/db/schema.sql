-- Argus Pentest Platform Database Schema
-- PostgreSQL 15+ with pgvector extension

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- Note: pgvector extension will be added later when available
-- CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Organizations table (multi-tenancy)
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    plan VARCHAR(50) NOT NULL DEFAULT 'free', -- free, pro, enterprise
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'user', -- admin, user, viewer
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP WITH TIME ZONE
);

-- Engagements table
CREATE TABLE engagements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_url VARCHAR(2048) NOT NULL,
    authorization_proof TEXT NOT NULL, -- Proof of authorization (renamed from 'authorization' to avoid reserved keyword)
    authorized_scope JSONB NOT NULL, -- {domains: [], ipRanges: []}
    status VARCHAR(50) NOT NULL DEFAULT 'created', -- created, recon, awaiting_approval, scanning, analyzing, reporting, complete, failed, paused
    rate_limit_config JSONB, -- {requestsPerSecond, concurrentRequests, respectRobotsTxt, adaptiveSlowdown}
    scan_type VARCHAR(50) NOT NULL DEFAULT 'url', -- 'url' for web app scan, 'repo' for repository scan
    scan_aggressiveness VARCHAR(20) NOT NULL DEFAULT 'default', -- default, high, extreme
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT valid_status CHECK (status IN ('created', 'recon', 'awaiting_approval', 'scanning', 'analyzing', 'reporting', 'complete', 'failed', 'paused'))
);

-- Loop budgets table
CREATE TABLE loop_budgets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL UNIQUE REFERENCES engagements(id) ON DELETE CASCADE,
    max_cycles INTEGER NOT NULL DEFAULT 5,
    max_depth INTEGER NOT NULL DEFAULT 3,
    max_cost DECIMAL(10, 2) NOT NULL DEFAULT 0.50,
    current_cycles INTEGER NOT NULL DEFAULT 0,
    current_depth INTEGER NOT NULL DEFAULT 0,
    current_cost DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Findings table
CREATE TABLE findings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    type VARCHAR(255) NOT NULL, -- SQL_INJECTION, XSS, IDOR, etc.
    severity VARCHAR(50) NOT NULL, -- CRITICAL, HIGH, MEDIUM, LOW, INFO
    confidence DECIMAL(3, 2) NOT NULL, -- 0.00 - 1.00
    endpoint VARCHAR(2048) NOT NULL,
    evidence JSONB NOT NULL, -- {request, response, payload, matchedPattern}
    source_tool VARCHAR(100) NOT NULL, -- nuclei, sqlmap, httpx, ffuf
    repro_steps TEXT[],
    cvss_score DECIMAL(3, 1),
    owasp_category VARCHAR(100),
    cwe_id VARCHAR(50),
    evidence_strength VARCHAR(50), -- verified, strong, moderate, weak
    tool_agreement_level VARCHAR(50), -- high, medium, low
    fp_likelihood DECIMAL(3, 2), -- 0.00 - 1.00
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_severity CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO')),
    CONSTRAINT valid_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT valid_fp_likelihood CHECK (fp_likelihood IS NULL OR (fp_likelihood >= 0 AND fp_likelihood <= 1))
);

-- Attack paths table
CREATE TABLE attack_paths (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    path_nodes JSONB NOT NULL, -- Array of {id, type, data, cvss, confidence}
    risk_score DECIMAL(4, 2) NOT NULL, -- 0.00 - 10.00
    normalized_severity DECIMAL(4, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_risk_score CHECK (risk_score >= 0 AND risk_score <= 10)
);

-- ============================================================================
-- STATE MANAGEMENT TABLES
-- ============================================================================

-- Engagement state transitions table
CREATE TABLE engagement_states (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    from_state VARCHAR(50),
    to_state VARCHAR(50) NOT NULL,
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Job states table (for Redis queue tracking)
CREATE TABLE job_states (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    job_type VARCHAR(50) NOT NULL, -- recon, scan, analyze, report
    status VARCHAR(50) NOT NULL DEFAULT 'queued', -- queued, processing, complete, failed
    worker_id VARCHAR(255),
    idempotency_key VARCHAR(255) UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT
);

-- Decision snapshots table
CREATE TABLE decision_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    snapshot_data JSONB NOT NULL, -- {findings, attackGraph, loopBudget, engagementState}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(engagement_id, version)
);

-- Checkpoints table (for recovery)
CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL, -- recon, scan, analyze, report
    data JSONB NOT NULL, -- Partial results
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- LOGGING AND MONITORING TABLES
-- ============================================================================

-- Execution logs table
CREATE TABLE execution_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID REFERENCES engagements(id) ON DELETE CASCADE,
    trace_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL, -- job_started, tool_executed, parser_completed, intelligence_decision
    message TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Execution spans table (for timeline)
CREATE TABLE execution_spans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trace_id UUID NOT NULL,
    span_name VARCHAR(255) NOT NULL, -- tool_execution, parsing, intelligence_evaluation, orchestrator_step
    duration_ms INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tool metrics table
CREATE TABLE tool_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tool_name VARCHAR(100) NOT NULL,
    duration_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Execution failures table
CREATE TABLE execution_failures (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    failure_type VARCHAR(100) NOT NULL, -- tool_crash, parser_failure, worker_death
    tool_name VARCHAR(100),
    error_message TEXT NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Raw outputs table (for unparseable tool outputs)
CREATE TABLE raw_outputs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    tool_name VARCHAR(100) NOT NULL,
    raw_output TEXT NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- SECURITY AND COMPLIANCE TABLES
-- ============================================================================

-- Scope violations table
CREATE TABLE scope_violations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    target_url VARCHAR(2048) NOT NULL,
    violation_type VARCHAR(100) NOT NULL, -- out_of_scope_domain, out_of_scope_ip
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Rate limit events table
CREATE TABLE rate_limit_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID REFERENCES engagements(id) ON DELETE CASCADE,
    domain VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL, -- throttle, backoff, circuit_breaker, rate_increase
    status_code INTEGER,
    current_rps DECIMAL(5, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Scanner activity log for live visibility into tool operations
CREATE TABLE scanner_activities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    tool_name VARCHAR(100) NOT NULL,
    activity TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'in_progress', -- started, in_progress, completed, failed
    target VARCHAR(2048),
    details TEXT,
    items_found INTEGER,
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- AI EXPLAINABILITY TABLES
-- ============================================================================

-- AI explainability traces table
CREATE TABLE ai_explainability_traces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_id UUID NOT NULL,
    input_cluster_ids UUID[] NOT NULL,
    used_fields TEXT[] NOT NULL,
    ignored_fields TEXT[],
    model_version VARCHAR(100) NOT NULL,
    token_count_input INTEGER NOT NULL,
    token_count_output INTEGER NOT NULL,
    reasoning_trace TEXT, -- First 500 chars of explanation
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Engagement indexes
CREATE INDEX idx_engagements_org_id ON engagements(org_id);
CREATE INDEX idx_engagements_created_by ON engagements(created_by);
CREATE INDEX idx_engagements_status ON engagements(status);
CREATE INDEX idx_engagements_created_at ON engagements(created_at);

-- Findings indexes
CREATE INDEX idx_findings_engagement_id ON findings(engagement_id);
CREATE INDEX idx_findings_severity ON findings(severity);
CREATE INDEX idx_findings_confidence ON findings(confidence);
CREATE INDEX idx_findings_source_tool ON findings(source_tool);
CREATE INDEX idx_findings_created_at ON findings(created_at);

-- Attack paths indexes
CREATE INDEX idx_attack_paths_engagement_id ON attack_paths(engagement_id);
CREATE INDEX idx_attack_paths_risk_score ON attack_paths(risk_score);

-- Execution logs indexes
CREATE INDEX idx_execution_logs_engagement_id ON execution_logs(engagement_id);
CREATE INDEX idx_execution_logs_trace_id ON execution_logs(trace_id);
CREATE INDEX idx_execution_logs_event_type ON execution_logs(event_type);
CREATE INDEX idx_execution_logs_created_at ON execution_logs(created_at);

-- Execution spans indexes
CREATE INDEX idx_execution_spans_trace_id ON execution_spans(trace_id);
CREATE INDEX idx_execution_spans_created_at ON execution_spans(created_at);

-- Tool metrics indexes
CREATE INDEX idx_tool_metrics_tool_name ON tool_metrics(tool_name);
CREATE INDEX idx_tool_metrics_created_at ON tool_metrics(created_at);

-- Job states indexes
CREATE INDEX idx_job_states_engagement_id ON job_states(engagement_id);
CREATE INDEX idx_job_states_status ON job_states(status);
CREATE INDEX idx_job_states_idempotency_key ON job_states(idempotency_key);

-- Scanner activities indexes
CREATE INDEX idx_scanner_activities_engagement_id ON scanner_activities(engagement_id);
CREATE INDEX idx_scanner_activities_created_at ON scanner_activities(created_at);

-- ============================================================================
-- FUNCTIONS AND TRIGGERS
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_engagements_updated_at BEFORE UPDATE ON engagements
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_loop_budgets_updated_at BEFORE UPDATE ON loop_budgets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- INITIAL DATA (Optional)
-- ============================================================================

-- Create default organization for development
INSERT INTO organizations (id, name, plan) VALUES 
    ('00000000-0000-0000-0000-000000000001', 'Default Organization', 'pro')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- USER SETTINGS TABLE
-- ============================================================================

-- User API keys and settings (encrypted storage)
CREATE TABLE user_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email VARCHAR(255) NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    key VARCHAR(100) NOT NULL,
    value TEXT, -- Encrypted for sensitive values
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_email, key)
);

-- Index for faster lookups
CREATE INDEX idx_user_settings_email ON user_settings(user_email);

-- ============================================================================
-- GRANTS (Adjust based on your user setup)
-- ============================================================================

-- ============================================================================
-- CUSTOM RULES TABLES (Step 27)
-- ============================================================================

CREATE TABLE custom_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    rule_yaml TEXT NOT NULL,
    severity VARCHAR(50) NOT NULL DEFAULT 'MEDIUM',
    category VARCHAR(100) NOT NULL DEFAULT 'custom',
    tags TEXT[],
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    parent_rule_id UUID REFERENCES custom_rules(id) ON DELETE SET NULL,
    test_results JSONB,
    is_community_shared BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_rule_status CHECK (status IN ('draft', 'active', 'deprecated', 'archived'))
);

CREATE TABLE custom_rule_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id UUID NOT NULL REFERENCES custom_rules(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    rule_yaml TEXT NOT NULL,
    change_notes TEXT,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(rule_id, version)
);

CREATE INDEX idx_custom_rules_org_id ON custom_rules(org_id);
CREATE INDEX idx_custom_rules_status ON custom_rules(status);
CREATE INDEX idx_custom_rules_category ON custom_rules(category);
CREATE INDEX idx_custom_rule_versions_rule_id ON custom_rule_versions(rule_id);

-- ============================================================================
-- ASSET INVENTORY TABLES (Step 28)
-- ============================================================================

CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    engagement_id UUID REFERENCES engagements(id) ON DELETE SET NULL,
    asset_type VARCHAR(100) NOT NULL, -- domain, ip, endpoint, repository, container, api
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

CREATE INDEX idx_assets_org_id ON assets(org_id);
CREATE INDEX idx_assets_engagement_id ON assets(engagement_id);
CREATE INDEX idx_assets_asset_type ON assets(asset_type);
CREATE INDEX idx_assets_risk_score ON assets(risk_score);
CREATE INDEX idx_assets_lifecycle_status ON assets(lifecycle_status);

-- ============================================================================
-- GRANTS (Adjust based on your user setup)
-- ============================================================================

-- Grant permissions to argus_user (if exists)
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'argus_user') THEN
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO argus_user;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO argus_user;
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO argus_user;
    END IF;
END
$$;
