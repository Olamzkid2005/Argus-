-- Migration 012: Add agent decision log table for LLM ReAct agent auditability.
--
-- Every LLM tool selection decision is persisted for debugging and
-- frontend visibility into what the agent chose and why.
BEGIN;

CREATE TABLE IF NOT EXISTS agent_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    iteration INTEGER NOT NULL,
    tool_selected VARCHAR(100) NOT NULL,
    arguments JSONB NOT NULL DEFAULT '{}',
    reasoning TEXT,
    was_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd DECIMAL(8, 6),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_engagement
    ON agent_decisions(engagement_id, created_at);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_created_at
    ON agent_decisions(created_at);

COMMIT;
