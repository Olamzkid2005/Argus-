-- Add auth_config column to engagements for authenticated scanning
ALTER TABLE engagements
ADD COLUMN IF NOT EXISTS auth_config JSONB DEFAULT '{}'::jsonb;
