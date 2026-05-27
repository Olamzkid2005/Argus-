-- Migration 043: Add priority_vuln_classes to engagements
-- Allows users to specify vulnerability classes that should be prioritized
-- during scanning and severity escalation.

ALTER TABLE engagements
ADD COLUMN IF NOT EXISTS priority_vuln_classes TEXT[] DEFAULT '{}';

-- Index on GIN for array containment queries
CREATE INDEX IF NOT EXISTS idx_engagements_priority_vuln_classes
ON engagements USING GIN (priority_vuln_classes);
