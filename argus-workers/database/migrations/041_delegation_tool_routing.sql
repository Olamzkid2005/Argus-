-- Migration 041: route subtasks to real tools.
--
-- Plan §4.6 requires every action to go through Argus's existing tool
-- registry, scope guard, approval and execution layer. The first cut stored
-- only title/description/dependencies, so a subtask could not name the tool
-- it needs and the executor had nothing real to invoke. These columns carry
-- the generator's tool routing: which tool to run and with which arguments.

ALTER TABLE delegation_subtasks
    ADD COLUMN IF NOT EXISTS tool TEXT;

ALTER TABLE delegation_subtasks
    ADD COLUMN IF NOT EXISTS arguments JSONB NOT NULL DEFAULT '{}';

COMMENT ON COLUMN delegation_subtasks.tool IS
    'Generator-supplied tool name this subtask must execute (e.g. semgrep, nuclei). NULL means the subtask carries no tool call and only fake/test executors may run it.';

COMMENT ON COLUMN delegation_subtasks.arguments IS
    'Generator-supplied tool arguments as a JSON object (argv list, timeout, approval record, specialist routing).';
