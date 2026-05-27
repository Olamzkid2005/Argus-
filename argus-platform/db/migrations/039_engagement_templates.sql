-- Migration 039: Engagement Templates
-- Saves reusable scan configurations for repeated assessments.
-- Templates store scan settings (not findings) so quarterly or recurring
-- scans can be created in seconds instead of reconfiguring from scratch.

CREATE TABLE IF NOT EXISTS engagement_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    config JSONB NOT NULL DEFAULT '{}',
    -- Config fields:
    --   target_url_pattern: string with {variable} substitution, e.g. "https://{subdomain}.example.com"
    --   scan_type: "url" | "repo"
    --   aggressiveness: "default" | "high" | "extreme"
    --   agent_mode: boolean
    --   scan_mode: "agent" | "swarm"
    --   auth_config_type: "form" | "bearer" | "cookie" | null
    --   priority_vuln_classes: string[]
    --   custom_rules: string[] (rule IDs)
    --   bug_bounty_platform: string | null
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_template_name_per_org UNIQUE (org_id, name)
);

CREATE INDEX idx_engagement_templates_org_id ON engagement_templates(org_id);
CREATE INDEX idx_engagement_templates_created_by ON engagement_templates(created_by);

-- Trigger for updated_at
CREATE TRIGGER update_engagement_templates_updated_at BEFORE UPDATE ON engagement_templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
