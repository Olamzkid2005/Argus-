-- Migration 023: Create users table
--
-- Problem: Several repositories reference org_id / user_id foreign keys but
-- no users table exists. This table is referenced by:
--   - engagement_repository.py (org_id on engagements)
--   - user_settings table (user_id foreign key)
--   - agent_prompts.py (user profile)
--   - Various audit log queries
--
-- Creates the users table with org membership and role-based access control.

BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member'
        CHECK (role IN ('admin', 'member', 'viewer', 'api')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, email)
);

CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(org_id, is_active) WHERE is_active = TRUE;

COMMIT;
