-- Stage 6.1: one cumulative budget record per engagement.
--
-- Stores the wall-clock deadline and the usage that must survive a resume:
-- LLM calls (including failed/fallback/malformed ones), tokens, cost (or the
-- fact that cost is unknown), tool calls, and request count. `engagement_id`
-- is the primary key, so a resumed run UPSERTs into the same row and keeps
-- accumulating instead of starting a fresh budget.

BEGIN;

CREATE TABLE IF NOT EXISTS engagement_budget_usage (
    engagement_id UUID PRIMARY KEY REFERENCES engagements(id) ON DELETE CASCADE,
    deadline_at TIMESTAMPTZ,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    llm_failures INTEGER NOT NULL DEFAULT 0,
    llm_fallbacks INTEGER NOT NULL DEFAULT 0,
    llm_malformed INTEGER NOT NULL DEFAULT 0,
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    cost_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
    cost_known BOOLEAN NOT NULL DEFAULT TRUE,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
