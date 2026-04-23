-- ============================================================================
-- EXECUTION LOG LEVEL MIGRATION (Step 27)
-- ============================================================================
--
-- Adds log_level to execution_logs for observability/log filtering endpoints.
-- Safe to run multiple times.

ALTER TABLE execution_logs
ADD COLUMN IF NOT EXISTS log_level VARCHAR(20);

UPDATE execution_logs
SET log_level = 'INFO'
WHERE log_level IS NULL;

ALTER TABLE execution_logs
ALTER COLUMN log_level SET DEFAULT 'INFO';

