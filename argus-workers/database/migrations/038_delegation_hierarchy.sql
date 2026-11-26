-- Migration 038: hierarchical task delegation
--
-- Durable Flow/Task/Subtask/Action hierarchy (plan §4.4). The Argus engagement is
-- the Flow, a Task is one authorized Investigation Intent / work package, and
-- Actions are the tool calls the existing executor performed for a Subtask.
--
-- The tables are written only by the delegation service / dispatcher. Agents
-- receive bounded payloads and return structured results; they never mutate
-- these rows directly.
--
-- NOTE: no explicit BEGIN/COMMIT here. The migration runner wraps each file in
-- its own transaction.

CREATE TABLE IF NOT EXISTS delegation_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    intent_id UUID,
    objective TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    generator_version INTEGER NOT NULL DEFAULT 1,
    task_context_ref TEXT,
    resolution TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT delegation_tasks_status_check CHECK (
        status IN ('created', 'running', 'waiting', 'finished', 'failed')
    )
);

COMMENT ON TABLE delegation_tasks IS 'Delegation Task / work package; engagement is the Flow.';
COMMENT ON COLUMN delegation_tasks.intent_id IS 'graph investigation intent node this task executes, when one exists.';

CREATE INDEX IF NOT EXISTS idx_delegation_tasks_engagement
    ON delegation_tasks(engagement_id, status);
CREATE INDEX IF NOT EXISTS idx_delegation_tasks_intent
    ON delegation_tasks(intent_id) WHERE intent_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS delegation_subtasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES delegation_tasks(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    required BOOLEAN NOT NULL DEFAULT TRUE,
    depends_on JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_ref TEXT,
    message_chain_ref TEXT,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    resolution TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT delegation_subtasks_ordinal_unique UNIQUE (task_id, ordinal),
    CONSTRAINT delegation_subtasks_status_check CHECK (
        status IN ('created', 'running', 'waiting', 'finished', 'failed', 'skipped', 'cancelled')
    )
);

COMMENT ON TABLE delegation_subtasks IS 'Ordered Task steps; order and status are durable across restarts.';
COMMENT ON COLUMN delegation_subtasks.depends_on IS 'Subtask IDs that must be terminal before this one may start.';
COMMENT ON COLUMN delegation_subtasks.resolution IS 'Explicit accepted-skip / failure resolution recorded before task completion.';
COMMENT ON COLUMN delegation_subtasks.result IS 'Persisted structured result used by the Reporter; never rewritten by a refiner patch.';

CREATE INDEX IF NOT EXISTS idx_delegation_subtasks_task
    ON delegation_subtasks(task_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_delegation_subtasks_status
    ON delegation_subtasks(task_id, status);

CREATE TABLE IF NOT EXISTS delegation_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subtask_id UUID NOT NULL REFERENCES delegation_subtasks(id) ON DELETE CASCADE,
    action_id TEXT NOT NULL,
    tool TEXT,
    canonical_arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_agent TEXT,
    reasoning_ref TEXT,
    outcome TEXT NOT NULL DEFAULT 'completed',
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    CONSTRAINT delegation_actions_idempotent UNIQUE (subtask_id, action_id)
);

COMMENT ON TABLE delegation_actions IS 'One tool operation inside a Subtask; the unique key makes replay idempotent.';

CREATE INDEX IF NOT EXISTS idx_delegation_actions_subtask
    ON delegation_actions(subtask_id, started_at);

CREATE TABLE IF NOT EXISTS delegation_patches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES delegation_tasks(id) ON DELETE CASCADE,
    trigger_subtask_id UUID REFERENCES delegation_subtasks(id) ON DELETE SET NULL,
    rationale TEXT,
    operations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE delegation_patches IS 'Exact refiner delta that was applied, with its rationale, for audit.';

CREATE INDEX IF NOT EXISTS idx_delegation_patches_task
    ON delegation_patches(task_id, created_at);

CREATE TABLE IF NOT EXISTS delegation_reports (
    task_id UUID PRIMARY KEY REFERENCES delegation_tasks(id) ON DELETE CASCADE,
    body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE delegation_reports IS 'One task-level report assembled from persisted results/evidence; written once.';

CREATE TABLE IF NOT EXISTS delegation_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    tenant_id UUID,
    kind TEXT NOT NULL DEFAULT 'fact',
    summary TEXT NOT NULL,
    redacted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE delegation_memory IS 'Redacted cross-task knowledge. Reads are tenant-scoped and never return secrets.';

CREATE INDEX IF NOT EXISTS idx_delegation_memory_tenant
    ON delegation_memory(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_delegation_memory_engagement
    ON delegation_memory(engagement_id, created_at DESC);
