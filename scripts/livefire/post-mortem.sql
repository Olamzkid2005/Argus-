-- ==========================================================================
-- post-mortem.sql — Argus Live-Fire Post-Mortem Analysis Queries
--
-- Run after a live-fire validation to analyze findings, timing, and
-- signal coverage. Replace 'a1b2c3d4-1111-4000-8000-000000000001' with
-- your actual engagement_id.
--
-- Usage:
--   docker compose exec -T postgres psql -U argus_user -d argus_pentest \
--     -v engagement_id='a1b2c3d4-1111-4000-8000-000000000001' \
--     -f scripts/livefire/post-mortem.sql
-- ==========================================================================

\set ON_ERROR_STOP on
\x on

-- ==========================================================================
-- 1. Engagement Timing
-- ==========================================================================
SELECT '=== ENGAGEMENT TIMING ===' as section;
SELECT 
  id,
  target_url,
  status,
  created_at,
  started_at,
  completed_at,
  EXTRACT(EPOCH FROM (started_at - created_at))::int as setup_delay_seconds,
  EXTRACT(EPOCH FROM (completed_at - started_at))::int as scan_duration_seconds,
  EXTRACT(EPOCH FROM (completed_at - created_at))::int as total_duration_seconds
FROM engagements 
WHERE id = :'engagement_id';

-- ==========================================================================
-- 2. Findings Severity Distribution
-- ==========================================================================
SELECT '=== FINDINGS BY SEVERITY ===' as section;
SELECT 
  severity,
  COUNT(*) as count,
  ROUND(AVG(confidence)::numeric, 3) as avg_confidence,
  ROUND(MIN(confidence)::numeric, 3) as min_confidence,
  ROUND(MAX(confidence)::numeric, 3) as max_confidence,
  COUNT(*) FILTER (WHERE verified = true) as verified_count,
  COUNT(*) FILTER (WHERE verified = false) as unverified_count,
  ROUND(COUNT(*) FILTER (WHERE verified = true) * 100.0 / NULLIF(COUNT(*), 0), 1) as verified_pct
FROM findings 
WHERE engagement_id = :'engagement_id'
GROUP BY severity
ORDER BY 
  CASE severity 
    WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 
    WHEN 'MEDIUM' THEN 3 WHEN 'LOW' THEN 4 WHEN 'INFO' THEN 5
    ELSE 6
  END;

-- ==========================================================================
-- 3. Finding Types (Top 20)
-- ==========================================================================
SELECT '=== TOP FINDING TYPES ===' as section;
SELECT 
  type,
  COUNT(*) as count,
  COUNT(DISTINCT endpoint) as unique_endpoints,
  ROUND(AVG(confidence)::numeric, 3) as avg_confidence
FROM findings 
WHERE engagement_id = :'engagement_id'
GROUP BY type
ORDER BY count DESC
LIMIT 20;

-- ==========================================================================
-- 4. Tool Productivity
-- ==========================================================================
SELECT '=== TOOL PRODUCTIVITY ===' as section;
SELECT 
  source_tool,
  COUNT(*) as findings_count,
  COUNT(DISTINCT type) as unique_finding_types,
  ROUND(AVG(confidence)::numeric, 3) as avg_confidence,
  COUNT(*) FILTER (WHERE severity IN ('CRITICAL', 'HIGH')) as critical_or_high
FROM findings 
WHERE engagement_id = :'engagement_id' AND source_tool IS NOT NULL
GROUP BY source_tool
ORDER BY findings_count DESC;

-- ==========================================================================
-- 5. Endpoint Coverage
-- ==========================================================================
SELECT '=== ENDPOINT COVERAGE ===' as section;
SELECT 
  endpoint,
  COUNT(*) as findings_count,
  COUNT(DISTINCT type) as unique_types,
  MAX(severity) as max_severity
FROM findings 
WHERE engagement_id = :'engagement_id' AND endpoint IS NOT NULL
GROUP BY endpoint
ORDER BY findings_count DESC
LIMIT 30;

-- ==========================================================================
-- 6. Verification Summary
-- ==========================================================================
SELECT '=== VERIFICATION SUMMARY ===' as section;
SELECT 
  COUNT(*) as total_findings,
  COUNT(*) FILTER (WHERE verified = true) as confirmed,
  COUNT(*) FILTER (WHERE verified = false AND confidence >= 0.5) as likely_false_positive,
  COUNT(*) FILTER (WHERE verified IS NULL) as not_verified,
  ROUND(AVG(confidence)::numeric, 3) as overall_avg_confidence,
  ROUND(COUNT(*) FILTER (WHERE verified = true) * 100.0 / NULLIF(COUNT(*), 0), 1) as confirmed_pct
FROM findings 
WHERE engagement_id = :'engagement_id';

-- ==========================================================================
-- 7. Swarm Agent Distribution (from evidence->>'source_agent')
-- ==========================================================================
SELECT '=== SWARM AGENT DISTRIBUTION ===' as section;
SELECT 
  evidence->>'source_agent' as agent,
  COUNT(*) as findings_count,
  COUNT(DISTINCT type) as unique_types,
  ROUND(AVG(confidence)::numeric, 3) as avg_confidence
FROM findings 
WHERE 
  engagement_id = :'engagement_id' 
  AND evidence->>'source_agent' IS NOT NULL
GROUP BY evidence->>'source_agent'
ORDER BY findings_count DESC;

-- ==========================================================================
-- 8. Known Vulnerability Coverage (Juice Shop specific)
-- ==========================================================================
SELECT '=== KNOWN VULNERABILITY COVERAGE ===' as section;

WITH coverage AS (
  SELECT
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND type ILIKE '%SQL%' OR type ILIKE '%INJECTION%') THEN '✅' ELSE '❌' END as sqli,
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND type ILIKE '%XSS%') THEN '✅' ELSE '❌' END as xss,
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND type ILIKE '%JWT%') THEN '✅' ELSE '❌' END as jwt,
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND (type ILIKE '%IDOR%' OR type ILIKE '%BOLA%')) THEN '✅' ELSE '❌' END as idor_bola,
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND (type ILIKE '%AUTH%' OR type ILIKE '%PRIVILEGE%' OR type ILIKE '%BYPASS%')) THEN '✅' ELSE '❌' END as auth_bypass,
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND type ILIKE '%CSRF%') THEN '✅' ELSE '❌' END as csrf,
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND type ILIKE '%SSRF%') THEN '✅' ELSE '❌' END as ssrf,
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND (type ILIKE '%RCE%' OR type ILIKE '%COMMAND%')) THEN '✅' ELSE '❌' END as rce,
    CASE WHEN EXISTS (SELECT 1 FROM findings WHERE engagement_id = :'engagement_id' AND type ILIKE '%OPEN_REDIRECT%' OR type ILIKE '%OPEN REDIRECT%') THEN '✅' ELSE '❌' END as open_redirect
)
SELECT 'SQL Injection' as vulnerability, sqli as found FROM coverage
UNION ALL SELECT 'XSS', xss FROM coverage
UNION ALL SELECT 'JWT Issues', jwt FROM coverage
UNION ALL SELECT 'IDOR / BOLA', idor_bola FROM coverage
UNION ALL SELECT 'Auth Bypass', auth_bypass FROM coverage
UNION ALL SELECT 'CSRF', csrf FROM coverage
UNION ALL SELECT 'SSRF', ssrf FROM coverage
UNION ALL SELECT 'RCE / Command Injection', rce FROM coverage
UNION ALL SELECT 'Open Redirect', open_redirect FROM coverage;

-- ==========================================================================
-- 9. Aggregate Metrics Dashboard
-- ==========================================================================
SELECT '=== METRICS DASHBOARD ===' as section;
SELECT
  (SELECT COUNT(*) FROM findings WHERE engagement_id = :'engagement_id') as total_findings,
  (SELECT COUNT(*) FROM findings WHERE engagement_id = :'engagement_id' AND severity = 'CRITICAL') as critical_count,
  (SELECT COUNT(*) FROM findings WHERE engagement_id = :'engagement_id' AND severity = 'HIGH') as high_count,
  (SELECT COUNT(*) FROM findings WHERE engagement_id = :'engagement_id' AND verified = true) as verified_count,
  (SELECT COUNT(DISTINCT source_tool) FROM findings WHERE engagement_id = :'engagement_id' AND source_tool IS NOT NULL) as unique_tools_used,
  (SELECT COUNT(DISTINCT type) FROM findings WHERE engagement_id = :'engagement_id') as unique_finding_types,
  (SELECT COUNT(DISTINCT endpoint) FROM findings WHERE engagement_id = :'engagement_id' AND endpoint IS NOT NULL) as unique_endpoints_affected,
  (SELECT ROUND(AVG(confidence)::numeric, 3) FROM findings WHERE engagement_id = :'engagement_id') as overall_avg_confidence;

\x off
