-- Migration 044: Link custom_rules to engagements
-- Junction table allowing rules to be scoped to specific engagements
-- rather than always applying at the org level.

CREATE TABLE IF NOT EXISTS engagement_custom_rules (
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    rule_id UUID NOT NULL REFERENCES custom_rules(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (engagement_id, rule_id)
);

CREATE INDEX IF NOT EXISTS idx_engagement_custom_rules_engagement_id
ON engagement_custom_rules(engagement_id);

CREATE INDEX IF NOT EXISTS idx_engagement_custom_rules_rule_id
ON engagement_custom_rules(rule_id);
