-- Migration 025: Consolidate redundant cwe/owasp column pairs
-- The base schema (001) created cwe TEXT and owasp TEXT.
-- Migration 006 added cwe_id TEXT and owasp_category TEXT.
-- Both column pairs coexist, causing confusion and potential inconsistency.
-- This migration copies any data from the old columns to the canonical ones,
-- then drops the old columns.

BEGIN;

-- Copy old column values to canonical columns where the canonical column is NULL
UPDATE findings
   SET cwe_id = cwe
 WHERE cwe IS NOT NULL
   AND cwe_id IS NULL;

UPDATE findings
   SET owasp_category = owasp
 WHERE owasp IS NOT NULL
   AND owasp_category IS NULL;

-- Drop the old, redundant columns
ALTER TABLE findings
  DROP COLUMN IF EXISTS cwe,
  DROP COLUMN IF EXISTS owasp;

COMMIT;
