-- Migration 005: Add pgvector support for finding similarity search
-- Requires: pgvector extension installed on PostgreSQL
--
-- This migration adds vector embeddings to the findings table for semantic
-- similarity search across findings in different engagements.

-- Create pgvector extension (must be superuser or extension already exists)
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding column to findings table
-- Uses vector type with 1536 dimensions (OpenAI text-embedding-3-small)
ALTER TABLE findings
ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- Create index for cosine similarity search
-- Uses ivfflat for better performance on large datasets
-- Or uses hnsw for best performance (requires PostgreSQL 15+)
DO $$
BEGIN
    -- Try to create HNSW index (PostgreSQL 15+)
    IF substring(current_setting('server_version_num'))::int >= 150000 THEN
        CREATE INDEX IF NOT EXISTS idx_findings_embedding_hnsw
        ON findings USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
    ELSE
        -- Fall back to IVFFlat index (requires data to be loaded first)
        CREATE INDEX IF NOT EXISTS idx_findings_embedding_ivfflat
        ON findings USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    END IF;
EXCEPTION
    WHEN duplicate_table THEN
        NULL; -- Index already exists
    WHEN feature_not_supported THEN
        RAISE NOTICE 'HNSW/IVFFlat not supported, similarity search will use sequential scan';
END $$;

-- Create function to find similar findings using cosine similarity
CREATE OR REPLACE FUNCTION find_similar_findings(
    p_embedding vector(1536),
    p_engagement_id UUID,
    p_threshold float DEFAULT 0.85,
    p_limit int DEFAULT 10
)
RETURNS TABLE (
    id UUID,
    type VARCHAR(100),
    severity VARCHAR(20),
    endpoint VARCHAR(500),
    similarity float,
    engagement_id UUID
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        f.id,
        f.type,
        f.severity,
        f.endpoint,
        1 - (f.embedding <=> p_embedding) AS similarity,
        f.engagement_id
    FROM findings f
    WHERE f.engagement_id != p_engagement_id
      AND f.embedding IS NOT NULL
      AND (f.embedding <=> p_embedding) <= (1 - p_threshold)
    ORDER BY f.embedding <=> p_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql
STABLE
PARALLEL SAFE;

-- Create function to generate embedding for text (requires OpenAI API key)
-- This is a placeholder that would call OpenAI's embedding API
CREATE OR REPLACE FUNCTION generate_embedding(text_content text)
RETURNS vector(1536) AS $$
DECLARE
    api_key TEXT;
    embedding векtor(1536);
BEGIN
    api_key := current_setting('app.openai_api_key', true);

    -- Placeholder: In production, this would call OpenAI API
    -- using the openai Python client
    RAISE NOTICE 'Embedding generation requires OpenAI API key';

    -- Return null if no API key
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
STABLE;

-- Comment documenting the embedding column
COMMENT ON COLUMN findings.embedding IS 'Vector embedding (1536 dims) for semantic similarity search. Generated using OpenAI text-embedding-3-small model.';

-- Enable vector type for this database
SELECT * FROM pg_extension WHERE extname = 'vector';