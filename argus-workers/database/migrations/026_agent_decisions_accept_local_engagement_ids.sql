-- Migration 013: let agent_decisions reference engagements outside PostgreSQL.
--
-- The column was `UUID NOT NULL REFERENCES engagements(id)`, which only fits the
-- Celery path where every engagement is a PostgreSQL row. An in-process run
-- (`argus assess`, the TUI/CLI default) keeps its engagement in SQLite with an
-- id like `ENG-muofqp0u-1m`, so every decision insert failed the UUID cast — and
-- `AgentDecisionRepository.log_decision` swallows that failure and returns None,
-- which is how the audit log stayed empty while looking wired up.
--
-- agent_decisions is an audit log that spans two stores, and a foreign key into
-- one of them cannot express that. The engagement id is opaque here: it may name
-- a PostgreSQL engagement or a local one.
BEGIN;

ALTER TABLE agent_decisions
    DROP CONSTRAINT IF EXISTS agent_decisions_engagement_id_fkey;

ALTER TABLE agent_decisions
    ALTER COLUMN engagement_id TYPE TEXT;

COMMIT;
