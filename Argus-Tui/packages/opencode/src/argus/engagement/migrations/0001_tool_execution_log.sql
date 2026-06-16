-- Tool execution log for adaptive scoring (deferred to v6)
-- Added 2026-06-04 as part of Pass 2 implementation.

CREATE TABLE IF NOT EXISTS tool_execution_log (
    id TEXT PRIMARY KEY,
    engagement_id TEXT NOT NULL REFERENCES engagements(id),
    tool_name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    capability TEXT NOT NULL,
    succeeded INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_exec_engagement ON tool_execution_log(engagement_id);
CREATE INDEX IF NOT EXISTS idx_tool_exec_tool ON tool_execution_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_exec_capability ON tool_execution_log(capability);
