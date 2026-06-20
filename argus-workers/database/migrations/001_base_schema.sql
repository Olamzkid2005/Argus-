-- Migration 001: Base Schema
-- Up: Creates core tables

BEGIN;

-- Enable pgvector extension if available
CREATE EXTENSION IF NOT EXISTS vector;

-- Engagements table
CREATE TABLE IF NOT EXISTS engagements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID,
    target TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CREATED',
    workflow TEXT NOT NULL DEFAULT 'default',
    workflow_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

-- Findings table
CREATE TABLE IF NOT EXISTS findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'MEDIUM',
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'PENDING',
    endpoint TEXT,
    description TEXT,
    evidence JSONB DEFAULT '{}',
    source_tool TEXT,
    phase TEXT,
    cve TEXT,
    cwe TEXT,
    owasp TEXT,
    remediation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_findings_engagement ON findings(engagement_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
CREATE INDEX IF NOT EXISTS idx_findings_type ON findings(type);

-- Feature flags table
CREATE TABLE IF NOT EXISTS feature_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flag_name TEXT NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- User settings table
CREATE TABLE IF NOT EXISTS user_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL UNIQUE,
    settings JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;

-- Down: Drops all tables created above
-- BEGIN;
-- DROP TABLE IF EXISTS user_settings;
-- DROP TABLE IF EXISTS feature_flags;
-- DROP TABLE IF EXISTS findings;
-- DROP TABLE IF EXISTS engagements;
-- COMMIT;
