-- Migration 006: Add extra columns to findings table for scanner compatibility
-- These columns are referenced by FindingRepository but were absent from the base schema.
-- Requirements: cvss_score, owasp_category, cwe_id, evidence_strength,
--               tool_agreement_level, fp_likelihood, verified, last_seen_at,
--               llm_reviewed, llm_analysis

BEGIN;

ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS cvss_score REAL,
  ADD COLUMN IF NOT EXISTS owasp_category TEXT,
  ADD COLUMN IF NOT EXISTS cwe_id TEXT,
  ADD COLUMN IF NOT EXISTS evidence_strength TEXT,
  ADD COLUMN IF NOT EXISTS tool_agreement_level TEXT,
  ADD COLUMN IF NOT EXISTS fp_likelihood REAL,
  ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS llm_reviewed BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS llm_analysis JSONB;

COMMIT;
