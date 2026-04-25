-- Migration 004: Add LLM analysis columns to findings table
-- 
-- Prerequisites: migration 003 (findings table must exist)
-- 
-- These columns support:
-- 1. LLM Response Analysis (Post-Response Intelligence) — stores LLM verdict on HTTP responses
-- 2. LLM-generated payload tracking (context-aware payloads)

BEGIN;

-- Add LLM review tracking columns to findings table
ALTER TABLE findings
ADD COLUMN IF NOT EXISTS llm_reviewed BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS llm_analysis JSONB DEFAULT NULL;

COMMENT ON COLUMN findings.llm_reviewed IS 'Whether this finding has been reviewed by LLM response analysis';
COMMENT ON COLUMN findings.llm_analysis IS 'LLM analysis result: {vulnerable: bool, confidence: float, evidence_quote: str, model: str, timestamp: str}';

-- Index for efficient querying of unreviewed findings
CREATE INDEX IF NOT EXISTS idx_findings_llm_reviewed
    ON findings(engagement_id, llm_reviewed)
    WHERE llm_reviewed = FALSE;

-- Index for confidence-based queries used by LLM review task
CREATE INDEX IF NOT EXISTS idx_findings_confidence_llm
    ON findings(engagement_id, confidence DESC)
    WHERE llm_reviewed = FALSE OR llm_reviewed IS NULL;

COMMIT;
