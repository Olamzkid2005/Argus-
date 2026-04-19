-- Audit logging table
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id UUID,
    details JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_logs_org_action ON audit_logs(org_id, action);
CREATE INDEX idx_audit_logs_user_created ON audit_logs(user_id, created_at DESC);

-- Function to log actions
CREATE OR REPLACE FUNCTION log_audit_event(
    p_user_id UUID,
    p_org_id UUID,
    p_action VARCHAR,
    p_resource_type VARCHAR,
    p_resource_id UUID DEFAULT NULL,
    p_details JSONB DEFAULT '{}'
) RETURNS UUID AS $$
DECLARE
    v_audit_id UUID;
BEGIN
    INSERT INTO audit_logs (user_id, org_id, action, resource_type, resource_id, details)
    VALUES (p_user_id, p_org_id, p_action, p_resource_type, p_resource_id, p_details)
    RETURNING id INTO v_audit_id;
    
    RETURN v_audit_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create audit logs for common actions
CREATE OR REPLACE FUNCTION trigger_audit_log() RETURNS TRIGGER AS $$
DECLARE
    v_user_id UUID;
    v_org_id UUID;
    v_action VARCHAR;
BEGIN
    -- Get current user from session
    SELECT current_setting('app.user_id', true) INTO v_user_id;
    SELECT current_setting('app.org_id', true) INTO v_org_id;
    
    -- Determine action based on operation
    IF TG_OP = 'INSERT' THEN
        v_action := 'create_' || TG_TABLE_NAME;
    ELSIF TG_OP = 'UPDATE' THEN
        v_action := 'update_' || TG_TABLE_NAME;
    ELSIF TG_OP = 'DELETE' THEN
        v_action := 'delete_' || TG_TABLE_NAME;
    END IF;
    
    -- Log the action
    PERFORM log_audit_event(
        v_user_id,
        v_org_id,
        v_action,
        TG_TABLE_NAME,
        NEW.id,
        to_jsonb(NEW)
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create triggers for key tables
DROP TRIGGER IF EXISTS audit_engagements_trigger ON engagements;
CREATE TRIGGER audit_engagements_trigger
AFTER INSERT OR UPDATE ON engagements
FOR EACH ROW EXECUTE FUNCTION trigger_audit_log();

DROP TRIGGER IF EXISTS audit_findings_trigger ON findings;
CREATE TRIGGER audit_findings_trigger
AFTER INSERT OR UPDATE ON findings
FOR EACH ROW EXECUTE FUNCTION trigger_audit_log();