// Dashboard stats aggregation
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const orgId = (session.user as { orgId?: string }).orgId;

    if (!orgId) {
      return NextResponse.json(
        { error: "Session missing org ID" },
        { status: 401 }
      );
    }

    const client = await pool.connect();

    try {
      // Get org stats
      const orgStats = await client.query(
        `
        SELECT 
          (SELECT COUNT(*) FROM engagements WHERE org_id = $1) as total_engagements,
          (SELECT COUNT(*) FROM engagements WHERE org_id = $1 AND status = 'complete') as completed,
          (SELECT COUNT(*) FROM engagements WHERE org_id = $1 AND status = 'failed') as failed,
          (SELECT COUNT(*) FROM engagements WHERE org_id = $1 AND status IN ('scanning', 'analyzing')) as in_progress
      `,
        [orgId],
      );

      // Get findings stats
      const findingsStats = await client.query(
        `
        SELECT 
          COUNT(*) as total_findings,
          COUNT(*) FILTER (WHERE severity = 'CRITICAL') as critical,
          COUNT(*) FILTER (WHERE severity = 'HIGH') as high,
          COUNT(*) FILTER (WHERE severity = 'MEDIUM') as medium,
          COUNT(*) FILTER (WHERE verified = true) as verified
        FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE e.org_id = $1
      `,
        [orgId],
      );

      // Get recent activity
      const recentActivity = await client.query(
        `
        SELECT 
          e.id, e.target_url, e.status, e.created_at,
          (SELECT COUNT(*) FROM findings f WHERE f.engagement_id = e.id) as findings_count
        FROM engagements e
        WHERE e.org_id = $1
        ORDER BY e.created_at DESC
        LIMIT 5
        `,
        [orgId],
      );

      return NextResponse.json({
        engagements: orgStats.rows[0],
        findings: findingsStats.rows[0],
        recent_engagements: recentActivity.rows,
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Dashboard stats error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch dashboard stats" },
      { status: 500 },
    );
  }
}
