// Organization-level analytics API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(req: NextRequest) {
  log.api('GET', '/api/analytics', { query: req.nextUrl.search });
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const range = searchParams.get("range") || "30d";
    const days = parseInt(range.replace("d", ""), 10) || 30;

    const client = await pool.connect();

    try {
      // Trend data: findings by severity over time
      const trendsResult = await client.query(
        `
        SELECT 
          DATE(f.created_at) as date,
          COUNT(*) FILTER (WHERE f.severity = 'CRITICAL') as critical,
          COUNT(*) FILTER (WHERE f.severity = 'HIGH') as high,
          COUNT(*) FILTER (WHERE f.severity = 'MEDIUM') as medium,
          COUNT(*) FILTER (WHERE f.severity = 'LOW') as low
        FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE e.org_id = $1
          AND f.created_at >= CURRENT_DATE - INTERVAL '${days} days'
        GROUP BY DATE(f.created_at)
        ORDER BY DATE(f.created_at) ASC
        `,
        [session.user.orgId],
      );

      // Engagement comparisons
      const comparisonsResult = await client.query(
        `
        SELECT 
          e.id,
          e.target_url,
          e.created_at,
          COALESCE((SELECT COUNT(*) FROM findings f WHERE f.engagement_id = e.id), 0) as findings_count,
          COALESCE((SELECT COUNT(*) FROM findings f WHERE f.engagement_id = e.id AND f.severity = 'CRITICAL'), 0) as critical_count,
          COALESCE((SELECT COUNT(*) FROM findings f WHERE f.engagement_id = e.id AND f.severity = 'HIGH'), 0) as high_count,
          COALESCE(EXTRACT(EPOCH FROM (e.completed_at - e.created_at)) / 60, 0) as duration_minutes
        FROM engagements e
        WHERE e.org_id = $1
        ORDER BY e.created_at DESC
        LIMIT 10
        `,
        [session.user.orgId],
      );

      // Tool usage breakdown
      const toolsResult = await client.query(
        `
        SELECT 
          f.source_tool,
          COUNT(*) as finding_count,
          AVG(f.confidence) as avg_confidence
        FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE e.org_id = $1
          AND f.created_at >= CURRENT_DATE - INTERVAL '${days} days'
        GROUP BY f.source_tool
        ORDER BY finding_count DESC
        `,
        [session.user.orgId],
      );

      // Monthly summary
      const monthlyResult = await client.query(
        `
        SELECT 
          DATE_TRUNC('month', f.created_at) as month,
          COUNT(*) as total_findings,
          COUNT(*) FILTER (WHERE f.severity = 'CRITICAL') as critical,
          COUNT(*) FILTER (WHERE f.verified = true) as verified
        FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE e.org_id = $1
          AND f.created_at >= CURRENT_DATE - INTERVAL '12 months'
        GROUP BY DATE_TRUNC('month', f.created_at)
        ORDER BY month ASC
        `,
        [session.user.orgId],
      );

      log.apiEnd('GET', '/api/analytics', 200, { range: `${days}d` });
      return NextResponse.json({
        trends: trendsResult.rows.map((r) => ({
          date: new Date(r.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
          critical: parseInt(r.critical) || 0,
          high: parseInt(r.high) || 0,
          medium: parseInt(r.medium) || 0,
          low: parseInt(r.low) || 0,
        })),
        comparisons: comparisonsResult.rows,
        tools: toolsResult.rows,
        monthly: monthlyResult.rows,
        range: `${days}d`,
        generated_at: new Date().toISOString(),
      });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Analytics error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to fetch analytics" }, { status: 500 });
  }
}
