-- Migration 022: Add missing columns to engagements table
--
-- Problem: Several repositories reference columns that don't exist in the
-- engagements table: target_url, authorization_proof, authorized_scope,
-- created_by, scan_type. The performance index migration (006) creates
-- indexes on these columns, which would fail on a fresh database.
--
-- The engagement_repository works around this by storing extra fields in
-- the metadata JSONB column. This migration adds proper columns so the
-- indexes work and the repository can use direct column access.

BEGIN;

-- Add target_url column for human-readable URL display
ALTER TABLE engagements
  ADD COLUMN IF NOT EXISTS target_url TEXT;

-- Add scan_type column ("url" or "repo" — used by scheduled tasks and intent parser)
ALTER TABLE engagements
  ADD COLUMN IF NOT EXISTS scan_type TEXT NOT NULL DEFAULT 'url';

-- Add authorization_proof for compliance/audit tracking (legal authorization doc ref)
ALTER TABLE engagements
  ADD COLUMN IF NOT EXISTS authorization_proof TEXT;

-- Add authorized_scope as JSONB (list of allowed targets, used by ScopeValidator)
ALTER TABLE engagements
  ADD COLUMN IF NOT EXISTS authorized_scope JSONB DEFAULT '[]'::jsonb;

-- Add created_by for user attribution
ALTER TABLE engagements
  ADD COLUMN IF NOT EXISTS created_by TEXT;

-- Recreate indexes that reference these columns (the original migration 006
-- created them but they silently fail when the columns don't exist).
-- IF NOT EXISTS ensures idempotency on re-run.

CREATE INDEX IF NOT EXISTS idx_engagements_target_url
ON engagements(target_url);

CREATE INDEX IF NOT EXISTS idx_engagements_scope_gin
ON engagements USING GIN (authorized_scope);

-- Covering index for engagement list queries
CREATE INDEX IF NOT EXISTS idx_engagements_covering
ON engagements(org_id, status, created_at DESC, target_url, scan_type);

-- Migrate existing data: copy target_url from metadata JSONB if column was null
UPDATE engagements
SET target_url = metadata->>'_target_url'
WHERE target_url IS NULL AND metadata->>'_target_url' IS NOT NULL;

UPDATE engagements
SET authorization_proof = metadata->>'_authorization_proof'
WHERE authorization_proof IS NULL AND metadata->>'_authorization_proof' IS NOT NULL;

UPDATE engagements
SET authorized_scope = (metadata->'_authorized_scope')::jsonb
WHERE authorized_scope IS NULL AND metadata->'_authorized_scope' IS NOT NULL;

UPDATE engagements
SET created_by = metadata->>'_created_by'
WHERE created_by IS NULL AND metadata->>'_created_by' IS NOT NULL;

COMMIT;
