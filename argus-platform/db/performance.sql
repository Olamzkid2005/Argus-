-- Create optimized database materializations
CREATE MATERIALIZED VIEW IF NOT EXISTS engagement_summary AS
SELECT 
    e.id,
    e.target_url,
    e.status,
    e.scan_type,
    o.name as org_name,
    COUNT(f.id) FILTER (WHERE f.severity = 'CRITICAL') as critical_count,
    COUNT(f.id) FILTER (WHERE f.severity = 'HIGH') as high_count,
    COUNT(f.id) FILTER (WHERE f.severity = 'MEDIUM') as medium_count,
    COUNT(f.id) FILTER (WHERE f.severity = 'LOW') as low_count,
    COUNT(f.id) as total_findings,
    COUNT(f.id) FILTER (WHERE f.verified = true) as verified_count,
    MAX(f.created_at) as latest_finding,
    e.created_at,
    e.completed_at
FROM engagements e
LEFT JOIN organizations o ON e.org_id = o.id
LEFT JOIN findings f ON e.id = f.engagement_id
GROUP BY e.id, o.name;

-- M-29: Refresh materialized view on a cooldown to prevent thousands of refreshes
-- during high-throughput scans. Uses CONCURRENTLY to avoid blocking reads.
-- Limit to one refresh per 60 seconds using a custom GUC variable.
CREATE OR REPLACE FUNCTION refresh_engagement_summary() RETURNS TRIGGER AS $$
DECLARE
    last_refresh TIMESTAMP;
BEGIN
    -- Get last refresh time from a custom GUC (session-local, reset on connection)
    BEGIN
        last_refresh := current_setting('app.last_mv_refresh')::TIMESTAMP;
    EXCEPTION WHEN OTHERS THEN
        last_refresh := NULL;
    END;

    IF last_refresh IS NULL OR NOW() - last_refresh > INTERVAL '60 seconds' THEN
        BEGIN
            PERFORM set_config('app.last_mv_refresh', NOW()::TEXT, false);
            REFRESH MATERIALIZED VIEW CONCURRENTLY engagement_summary;
        EXCEPTION WHEN OTHERS THEN
            -- If CONCURRENTLY fails (e.g., no unique index), fall back to regular refresh
            REFRESH MATERIALIZED VIEW engagement_summary;
        END;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger (per-statement, not per-row, to reduce refresh frequency)
DROP TRIGGER IF EXISTS refresh_summary_trigger ON findings;
CREATE TRIGGER refresh_summary_trigger
AFTER INSERT OR UPDATE OR DELETE ON findings
FOR EACH STATEMENT EXECUTE FUNCTION refresh_engagement_summary();

-- Add a unique index to support CONCURRENTLY refresh
CREATE UNIQUE INDEX IF NOT EXISTS idx_engagement_summary_id ON engagement_summary(id);

-- Add Redis caching helper functions
CREATE OR REPLACE FUNCTION cache_get(key TEXT) RETURNS TEXT AS $$
DECLARE
    result TEXT;
BEGIN
    -- Using Redis via SQL
    PERFORM redis_get(key);
    -- This is a placeholder - actual implementation would use redis_fdw or similar
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Add cache expiration helper
CREATE OR REPLACE FUNCTION cache_set(key TEXT, value TEXT, expiry_seconds INT DEFAULT 3600) RETURNS BOOLEAN AS $$
BEGIN
    -- Placeholder for Redis SETEX
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- Optimize findings query with lateral join limitation
CREATE OR REPLACE FUNCTION get_findings_with_limits(
    p_engagement_id UUID,
    p_offset INT DEFAULT 0,
    p_limit INT DEFAULT 50
) RETURNS TABLE(
    id UUID,
    type VARCHAR,
    severity VARCHAR,
    endpoint VARCHAR,
    source_tool VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        f.id,
        f.type,
        f.severity,
        f.endpoint,
        f.source_tool,
        f.created_at
    FROM findings f
    WHERE f.engagement_id = p_engagement_id
    ORDER BY 
        CASE f.severity 
            WHEN 'CRITICAL' THEN 1 
            WHEN 'HIGH' THEN 2 
            WHEN 'MEDIUM' THEN 3 
            WHEN 'LOW' THEN 4 
            ELSE 5 
        END,
        f.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;