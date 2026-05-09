-- Step 19: Developer Fix Assistant — add remediation_fix column to findings
-- Migration: 038

ALTER TABLE findings ADD COLUMN remediation_fix JSONB;
ALTER TABLE findings ADD COLUMN remediation_fix_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN findings.remediation_fix IS
  'JSONB with {vulnerable_pattern, fixed_pattern, explanation, unit_test, library_recommendation, additional_contexts, tech_stack, generated_at}';

CREATE INDEX idx_findings_has_remediation ON findings((remediation_fix IS NOT NULL));
