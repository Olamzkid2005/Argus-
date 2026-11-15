-- Migration 031: Make findings.title insertable by normalizers that omit it.
--
-- Findings are persisted through batch_create_or_update, whose insert does not
-- supply title. The table declared title NOT NULL without a default, so every
-- scan finding was rolled back ("null value in column title") and the run
-- completed with zero persisted findings.

ALTER TABLE findings
  ALTER COLUMN title SET DEFAULT '';

UPDATE findings SET title = type WHERE title IS NULL;
