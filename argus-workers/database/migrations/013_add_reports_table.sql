-- Migration 013: Add reports table for LLM-generated reports.
--
-- Stores the structured report produced by the LLM report generator.
-- Uses a unique index to ensure one report per engagement (upsert).
BEGIN;

CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    generated_by VARCHAR(50) NOT NULL DEFAULT 'llm',
    executive_summary TEXT,
    full_report_json JSONB NOT NULL DEFAULT '{}',
    risk_level VARCHAR(20),
    total_findings INTEGER DEFAULT 0,
    critical_count INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,
    medium_count INTEGER DEFAULT 0,
    low_count INTEGER DEFAULT 0,
    model_used VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_engagement
    ON reports(engagement_id);

COMMIT;
