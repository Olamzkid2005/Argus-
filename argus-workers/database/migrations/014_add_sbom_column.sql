-- Migration 014: Add sbom_json column to reports table for CycloneDX SBOM storage.
--
-- Stores the Software Bill of Materials generated from dependency findings
-- as a JSONB column alongside the existing full_report_json.
BEGIN;

ALTER TABLE reports
ADD COLUMN IF NOT EXISTS sbom_json JSONB DEFAULT NULL;

COMMENT ON COLUMN reports.sbom_json IS 'CycloneDX JSON Software Bill of Materials generated from dependency findings';

COMMIT;
