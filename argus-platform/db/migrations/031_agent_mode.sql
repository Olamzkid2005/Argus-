-- Agent Mode toggle for engagements
ALTER TABLE engagements ADD COLUMN IF NOT EXISTS agent_mode BOOLEAN NOT NULL DEFAULT FALSE;
