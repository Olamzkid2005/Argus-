-- Initial Argus V5 schema migration
-- Generated from: src/argus/engagement/schema.sql.ts
-- Applied automatically by EngagementStore.ensureTables() on startup.
-- Run `bun drizzle-kit push` to apply, or rely on the auto-create in store.ts.
--
-- NOTE: The execution_spans table (Postgres, created by argus-workers tracing.py)
-- is @deprecated as of 2026-06-04. The OTel exporter replaced DB-backed span
-- storage. The table still exists in existing databases for backward compat
-- but is no longer written to. Safe to drop once no deployments rely on it.

CREATE TABLE IF NOT EXISTS engagements (
    id TEXT PRIMARY KEY,
    target TEXT NOT NULL,
    workflow TEXT NOT NULL,
    workflow_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'CREATED',
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    engagement_id TEXT NOT NULL REFERENCES engagements(id),
    title TEXT NOT NULL,
    severity INTEGER NOT NULL,
    confidence INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    description TEXT,
    subtype TEXT,
    cve TEXT,
    cwe TEXT,
    owasp TEXT,
    remediation TEXT,
    tool TEXT,
    phase TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    finalized_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_findings_engagement ON findings(engagement_id);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);

CREATE TABLE IF NOT EXISTS phases (
    id TEXT PRIMARY KEY,
    engagement_id TEXT NOT NULL REFERENCES engagements(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    capabilities TEXT DEFAULT '[]',
    execution_mode TEXT,
    started_at INTEGER,
    completed_at INTEGER,
    error TEXT,
    replan_cycle INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_phases_engagement ON phases(engagement_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    engagement_id TEXT NOT NULL REFERENCES engagements(id),
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_engagement ON audit_log(engagement_id);

CREATE TABLE IF NOT EXISTS evidence_packages (
    id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL REFERENCES findings(id),
    package_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_packages_finding ON evidence_packages(finding_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES evidence_packages(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    type TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_package ON artifacts(package_id);

CREATE TABLE IF NOT EXISTS workflow_snapshots (
    id TEXT PRIMARY KEY,
    engagement_id TEXT NOT NULL REFERENCES engagements(id),
    workflow_name TEXT NOT NULL,
    workflow_version INTEGER NOT NULL,
    workflow_yaml TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_snapshots_engagement ON workflow_snapshots(engagement_id);

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
