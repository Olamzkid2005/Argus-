-- Migration 039: persist the generator's expected completion condition.
--
-- Plan §4.5 generates {title, description, dependency list, expected completion
-- condition}. The first cut stored title/description/dependencies but silently
-- dropped the completion condition, so a durable acceptance predicate could not
-- be read back by the worker or the Reporter.

ALTER TABLE delegation_subtasks
    ADD COLUMN IF NOT EXISTS completion_condition TEXT;

COMMENT ON COLUMN delegation_subtasks.completion_condition IS
    'Generator-supplied expected completion condition for this subtask, when one was proposed.';
