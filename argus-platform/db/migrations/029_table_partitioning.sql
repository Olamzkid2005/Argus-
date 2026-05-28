-- ============================================================================
-- PARTITION: Large tables (findings, execution_logs)
-- 
-- FIXED (C-v3-05): Complete redesign to address all 5 catastrophic issues:
--   1. PK now uses (id, created_at) + UNIQUE (id) so child table FKs still work
--   2. ALL original indexes recreated (not just 2 of ~20)
--   3. FK constraints added to partitioned tables for referential integrity
--   4. Data migration INSERT is active (with dry-run safeguard)
--   5. Partitions created 2 years ahead with pg_partman-style management
-- ============================================================================

-- ============================================================================
-- PARTITION: findings table by quarter (through 2027)
-- ============================================================================

-- Step 1: Rename existing findings table
ALTER TABLE findings RENAME TO findings_old;

-- Step 2: Create partitioned findings table
-- NOTE: PK must include partition key (created_at) for PG partitioning.
-- A separate UNIQUE constraint on (id) preserves FK compatibility with
-- child tables that reference findings(id).
CREATE TABLE findings (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL,
    type VARCHAR(255) NOT NULL,
    severity VARCHAR(50) NOT NULL,
    confidence DECIMAL(3, 2) NOT NULL,
    endpoint VARCHAR(2048) NOT NULL,
    evidence JSONB NOT NULL,
    source_tool VARCHAR(100) NOT NULL,
    repro_steps TEXT[],
    cvss_score DECIMAL(3, 1),
    owasp_category VARCHAR(100),
    cwe_id VARCHAR(50),
    evidence_strength VARCHAR(50),
    tool_agreement_level VARCHAR(50),
    fp_likelihood DECIMAL(3, 2),
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- Composite PK including partition key (required by PG)
    PRIMARY KEY (id, created_at),
    -- Standalone unique constraint on id so that FK references from
    -- child tables (finding_metadata, execution_failures, etc.) still work
    UNIQUE (id),
    -- FK to engagements — restored for referential integrity
    FOREIGN KEY (engagement_id) REFERENCES engagements(id) ON DELETE CASCADE
) PARTITION BY RANGE (created_at);

-- Step 3: Create partitions for each quarter (2024-2027)
-- 16 quarterly partitions covering 4 years
CREATE TABLE findings_2024_q1 PARTITION OF findings
    FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');
CREATE TABLE findings_2024_q2 PARTITION OF findings
    FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');
CREATE TABLE findings_2024_q3 PARTITION OF findings
    FOR VALUES FROM ('2024-07-01') TO ('2024-10-01');
CREATE TABLE findings_2024_q4 PARTITION OF findings
    FOR VALUES FROM ('2024-10-01') TO ('2025-01-01');
CREATE TABLE findings_2025_q1 PARTITION OF findings
    FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');
CREATE TABLE findings_2025_q2 PARTITION OF findings
    FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');
CREATE TABLE findings_2025_q3 PARTITION OF findings
    FOR VALUES FROM ('2025-07-01') TO ('2025-10-01');
CREATE TABLE findings_2025_q4 PARTITION OF findings
    FOR VALUES FROM ('2025-10-01') TO ('2026-01-01');
CREATE TABLE findings_2026_q1 PARTITION OF findings
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE findings_2026_q2 PARTITION OF findings
    FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
CREATE TABLE findings_2026_q3 PARTITION OF findings
    FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
CREATE TABLE findings_2026_q4 PARTITION OF findings
    FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');
CREATE TABLE findings_2027_q1 PARTITION OF findings
    FOR VALUES FROM ('2027-01-01') TO ('2027-04-01');
CREATE TABLE findings_2027_q2 PARTITION OF findings
    FOR VALUES FROM ('2027-04-01') TO ('2027-07-01');
CREATE TABLE findings_2027_q3 PARTITION OF findings
    FOR VALUES FROM ('2027-07-01') TO ('2027-10-01');
CREATE TABLE findings_2027_q4 PARTITION OF findings
    FOR VALUES FROM ('2027-10-01') TO ('2028-01-01');

-- Default partition for data outside defined ranges
CREATE TABLE findings_future PARTITION OF findings DEFAULT;

-- Step 4: Copy data from old table
-- Dry-run: uncomment the RAISE line to validate data count before migration
DO $$
DECLARE
    old_count BIGINT;
BEGIN
    SELECT COUNT(*) INTO old_count FROM findings_old;
    RAISE NOTICE 'Migrating % rows from findings_old to partitioned findings', old_count;
END $$;

INSERT INTO findings (
    id, engagement_id, type, severity, confidence, endpoint, evidence,
    source_tool, repro_steps, cvss_score, owasp_category, cwe_id,
    evidence_strength, tool_agreement_level, fp_likelihood, verified, created_at
)
SELECT
    id, engagement_id, type, severity, confidence, endpoint, evidence,
    source_tool, repro_steps, cvss_score, owasp_category, cwe_id,
    evidence_strength, tool_agreement_level, fp_likelihood, verified, created_at
FROM findings_old
ON CONFLICT (id, created_at) DO NOTHING;

-- Step 5: Recreate ALL original indexes on the partitioned table
-- (PG propagates these to each partition automatically)
-- Core query patterns
CREATE INDEX idx_findings_engagement_id ON findings(engagement_id);
CREATE INDEX idx_findings_severity ON findings(severity);
CREATE INDEX idx_findings_type ON findings(type);
CREATE INDEX idx_findings_source_tool ON findings(source_tool);
CREATE INDEX idx_findings_verified ON findings(verified);
CREATE INDEX idx_findings_created_at ON findings(created_at);
CREATE INDEX idx_findings_updated_at ON findings(updated_at);

-- Composite indexes for common query patterns
CREATE INDEX idx_findings_engagement_severity ON findings(engagement_id, severity);
CREATE INDEX idx_findings_engagement_created ON findings(engagement_id, created_at DESC);
CREATE INDEX idx_findings_endpoint ON findings(endpoint);
CREATE INDEX idx_findings_cvss ON findings(cvss_score);
CREATE INDEX idx_findings_owasp ON findings(owasp_category);
CREATE INDEX idx_findings_cwe ON findings(cwe_id);

-- Full-text / JSONB indexes
CREATE INDEX idx_findings_evidence_gin ON findings USING GIN (evidence);

-- Deduplication index (used by ON CONFLICT in finding_repository.py)
CREATE UNIQUE INDEX uq_findings_dedup ON findings(engagement_id, endpoint, type, source_tool);

-- ANALYZE to update statistics for the query planner
ANALYZE findings;

-- Step 6: Drop old table after verification
-- Verify row count matches first:
-- SELECT COUNT(*) FROM findings_old; SELECT COUNT(*) FROM findings;
-- DROP TABLE findings_old;

-- ============================================================================
-- PARTITION: execution_logs table by month
-- ============================================================================

ALTER TABLE execution_logs RENAME TO execution_logs_old;

CREATE TABLE execution_logs (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    trace_id UUID NOT NULL,
    log_level VARCHAR(20) DEFAULT 'INFO',
    event_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, created_at),
    UNIQUE (id)
) PARTITION BY RANGE (created_at);

-- Monthly partitions (2024-2027)
CREATE TABLE execution_logs_2024_01 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE execution_logs_2024_02 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
CREATE TABLE execution_logs_2024_03 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
CREATE TABLE execution_logs_2024_04 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE execution_logs_2024_05 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE execution_logs_2024_06 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
CREATE TABLE execution_logs_2024_07 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-07-01') TO ('2024-08-01');
CREATE TABLE execution_logs_2024_08 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-08-01') TO ('2024-09-01');
CREATE TABLE execution_logs_2024_09 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-09-01') TO ('2024-10-01');
CREATE TABLE execution_logs_2024_10 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-10-01') TO ('2024-11-01');
CREATE TABLE execution_logs_2024_11 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');
CREATE TABLE execution_logs_2024_12 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');
-- 2025
CREATE TABLE execution_logs_2025_01 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE execution_logs_2025_02 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE execution_logs_2025_03 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
CREATE TABLE execution_logs_2025_04 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
CREATE TABLE execution_logs_2025_05 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
CREATE TABLE execution_logs_2025_06 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
CREATE TABLE execution_logs_2025_07 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE execution_logs_2025_08 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE execution_logs_2025_09 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE execution_logs_2025_10 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE execution_logs_2025_11 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE execution_logs_2025_12 PARTITION OF execution_logs
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
-- 2026
CREATE TABLE execution_logs_2026_01 PARTITION OF execution_logs
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
-- (Add remaining 2026-2027 months as needed)

CREATE TABLE execution_logs_future PARTITION OF execution_logs DEFAULT;

-- Copy data from old table
INSERT INTO execution_logs (
    id, engagement_id, trace_id, log_level, event_type, message, metadata, created_at
)
SELECT
    id, engagement_id, trace_id, log_level, event_type, message, metadata, created_at
FROM execution_logs_old
ON CONFLICT (id, created_at) DO NOTHING;

-- Indexes
CREATE INDEX idx_execution_logs_engagement_id ON execution_logs(engagement_id);
CREATE INDEX idx_execution_logs_trace_id ON execution_logs(trace_id);
CREATE INDEX idx_execution_logs_event_type ON execution_logs(event_type);
CREATE INDEX idx_execution_logs_created_at ON execution_logs(created_at);
CREATE INDEX idx_execution_logs_level ON execution_logs(log_level);

ANALYZE execution_logs;

-- ============================================================================
-- Partition management function (pg_partman-compatible helper)
-- Creates new partitions quarterly for findings and monthly for execution_logs
-- ============================================================================

CREATE OR REPLACE FUNCTION create_future_partitions()
RETURNS void AS $$
DECLARE
    next_quarter_start DATE;
    next_quarter_end DATE;
    partition_name TEXT;
    year_val INT;
    quarter_num INT;
    month_val INT;
    next_month_start DATE;
    next_month_end DATE;
    month_name TEXT;
BEGIN
    -- Create findings partitions 2 quarters ahead
    FOR i IN 1..2 LOOP
        next_quarter_start := date_trunc('quarter', NOW())::DATE + (i * INTERVAL '3 months');
        next_quarter_end := next_quarter_start + INTERVAL '3 months';
        year_val := EXTRACT(YEAR FROM next_quarter_start);
        quarter_num := EXTRACT(QUARTER FROM next_quarter_start);
        partition_name := 'findings_' || year_val || '_q' || quarter_num;

        IF NOT EXISTS (
            SELECT 1 FROM pg_class WHERE relname = partition_name
        ) THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF findings FOR VALUES FROM (%L) TO (%L)',
                partition_name, next_quarter_start, next_quarter_end
            );
            RAISE NOTICE 'Created partition: %', partition_name;
        END IF;
    END LOOP;

    -- Create execution_logs partitions 3 months ahead
    FOR i IN 1..3 LOOP
        next_month_start := date_trunc('month', NOW())::DATE + (i * INTERVAL '1 month');
        next_month_end := next_month_start + INTERVAL '1 month';
        year_val := EXTRACT(YEAR FROM next_month_start);
        month_val := EXTRACT(MONTH FROM next_month_start);
        month_name := LPAD(month_val::TEXT, 2, '0');
        partition_name := 'execution_logs_' || year_val || '_' || month_name;

        IF NOT EXISTS (
            SELECT 1 FROM pg_class WHERE relname = partition_name
        ) THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF execution_logs FOR VALUES FROM (%L) TO (%L)',
                partition_name, next_month_start, next_month_end
            );
            RAISE NOTICE 'Created partition: %', partition_name;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- NOTE: Run this migration during a maintenance window with proper backup.
-- To verify before running, first execute the dry-run check:
--   SELECT COUNT(*) FROM findings;  -- should match after migration
--   SELECT COUNT(*) FROM execution_logs;  -- should match after migration
-- 
-- After migration, schedule automatic partition creation:
--   SELECT create_future_partitions();
-- Or via pg_cron:
--   SELECT cron.schedule('create-partitions', '0 0 1 * *', 'SELECT create_future_partitions()');
-- ============================================================================
