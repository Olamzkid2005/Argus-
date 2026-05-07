// API v2 route wrapper for versioning
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

// Tool performance metrics endpoint
export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);

    const tool = searchParams.get("tool");
    const days = parseInt(searchParams.get("days") || "7");
    const limit = parseInt(searchParams.get("limit") || "20");

    const client = await pool.connect();

    try {
      const orgId = (session.user as { orgId?: string }).orgId;

      let query = `
        SELECT 
          tm.tool_name,
          COUNT(*) as run_count,
          AVG(duration_ms) as avg_duration_ms,
          MIN(duration_ms) as min_duration_ms,
          MAX(duration_ms) as max_duration_ms,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) as median_duration_ms,
          SUM(CASE WHEN success = true THEN 1 ELSE 0 END)::float / COUNT(*) * 100 as success_rate
        FROM tool_metrics tm
        JOIN engagements e ON e.id = tm.engagement_id
        WHERE e.org_id = $1
          AND tm.created_at > NOW() - INTERVAL '1 day' * $2
      `;
      const params: unknown[] = [orgId, days];
      let paramIndex = 3;

      if (tool) {
        query += ` AND tm.tool_name = $${paramIndex}`;
        params.push(tool);
        paramIndex++;
      }

      query += ` GROUP BY tm.tool_name ORDER BY run_count DESC LIMIT $${paramIndex}`;
      params.push(limit);

      const result = await client.query(query, params);

      // Get recent failures
      const failuresQuery = `
        SELECT ef.tool_name, ef.error_message, ef.created_at 
        FROM execution_failures ef
        JOIN engagements e ON e.id = ef.engagement_id
        WHERE e.org_id = $1
          AND ef.created_at > NOW() - INTERVAL '1 day' * $2
        ORDER BY ef.created_at DESC 
        LIMIT 10
      `;
      const failuresResult = await client.query(failuresQuery, [orgId, days]);

      return NextResponse.json({
        metrics: result.rows,
        recent_failures: failuresResult.rows,
        period_days: days,
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Metrics API error:", error);
    return NextResponse.json(
      { error: "Failed to fetch metrics" },
      { status: 500 },
    );
  }
}
