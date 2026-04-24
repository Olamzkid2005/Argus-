-- Partition large tables for performance
-- PostgreSQL native partitioning

-- ============================================================================
-- PARTITION: findings table by quarter (2024-2025)
-- ============================================================================

-- Convert findings to partitioned table
-- This requires recreating the table - run with care in production

-- Step 1: Rename existing findings table
ALTER TABLE findings RENAME TO findings_old;

-- Step 2: Create partitioned findings table
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
    -- Partition key
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Step 3: Create partitions for each quarter
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

-- Default partition for new data
CREATE TABLE findings_future PARTITION OF findings
    FOR VALUES FROM (MINVALUE) TO (MAXVALUE);

-- Step 4: Copy data from old table (will take time for large datasets)
-- INSERT INTO findings SELECT * FROM findings_old;

-- Step 5: Add indexes (will be created per partition automatically in PG16+)
CREATE INDEX idx_findings_engagement_id ON findings(engagement_id);
CREATE INDEX idx_findings_severity ON findings(severity);

-- Step 6: Drop old table after verification
-- DROP TABLE findings_old;

-- ============================================================================
-- PARTITION: execution_logs table by month
-- ============================================================================

-- Same pattern for execution_logs
ALTER TABLE execution_logs RENAME TO execution_logs_old;

CREATE TABLE execution_logs (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    engagement_id UUID,
    trace_id UUID NOT NULL,
    log_level VARCHAR(20) DEFAULT 'INFO',
    event_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Monthly partitions
CREATE TABLE execution_logs_2024_01 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE execution_logs_2024_02 PARTITION OF execution_logs
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

-- Continue pattern for other months...

CREATE TABLE execution_logs_future PARTITION OF execution_logs
    FOR VALUES FROM (MINVALUE) TO (MAXVALUE);

-- Indexes
CREATE INDEX idx_execution_logs_engagement_id ON execution_logs(engagement_id);
CREATE INDEX idx_execution_logs_trace_id ON execution_logs(trace_id);
CREATE INDEX idx_execution_logs_event_type ON execution_logs(event_type);

-- ============================================================================
-- NOTE: Partitioning is complex and requires careful migration
-- This script provides the structure - actual migration should be done
-- during a maintenance window with proper backup
-- ============================================================================
-- 
-- Quick partition check query:
-- SELECT 
--   schemaname, 
--   tablename, 
--   parttypename, 
--   partname 
-- FROM pg_partitions 
-- WHERE schemaname = 'public';
-- ============================================================================