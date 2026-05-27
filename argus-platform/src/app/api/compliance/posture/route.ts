// Compliance Posture API — org-level posture summary + per-engagement detail
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(req: NextRequest) {
  log.api('GET', '/api/compliance/posture', { query: req.nextUrl.search });
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const engagementId = searchParams.get("engagement_id");

    const client = await pool.connect();

    try {
      if (engagementId) {
        // Per-engagement posture: latest snapshot + history
        const latestResult = await client.query(
          `SELECT id, engagement_id, composite_score, framework_scores,
                  total_findings, trend, previous_score, computed_at
           FROM compliance_posture_snapshots
           WHERE engagement_id = $1
           ORDER BY computed_at DESC
           LIMIT 1`,
          [engagementId],
        );

        const historyResult = await client.query(
          `SELECT id, engagement_id, composite_score, framework_scores,
                  total_findings, trend, computed_at
           FROM compliance_posture_snapshots
           WHERE engagement_id = $1
           ORDER BY computed_at DESC
           LIMIT 20`,
          [engagementId],
        );

        return NextResponse.json({
          latest: latestResult.rows[0] || null,
          history: historyResult.rows || [],
        });
      }

      // Org-level summary: latest snapshot per engagement
      const orgResult = await client.query(
        `SELECT DISTINCT ON (cps.engagement_id)
            cps.engagement_id,
            e.target_url,
            cps.composite_score,
            cps.total_findings,
            cps.trend,
            cps.framework_scores,
            cps.computed_at
         FROM compliance_posture_snapshots cps
         JOIN engagements e ON cps.engagement_id = e.id
         WHERE e.org_id = $1
         ORDER BY cps.engagement_id, cps.computed_at DESC`,
        [session.user.orgId],
      );

      const engagements = orgResult.rows || [];
      let avgScore = 100.0;
      if (engagements.length > 0) {
        const total = engagements.reduce((sum, r) => sum + parseFloat(r.composite_score || 100), 0);
        avgScore = Math.round((total / engagements.length) * 10) / 10;
      }

      // Count by severity across all engagements
      const severityResult = await client.query(
        `SELECT severity, COUNT(*) as count
         FROM findings f
         JOIN engagements e ON f.engagement_id = e.id
         WHERE e.org_id = $1
         GROUP BY severity`,
        [session.user.orgId],
      );

      const severityCounts: Record<string, number> = {
        CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0,
      };
      for (const row of severityResult.rows) {
        severityCounts[row.severity] = parseInt(row.count, 10);
      }

      // Trend over time: aggregate composite scores per day
      const trendResult = await client.query(
        `SELECT DATE(cps.computed_at) as day,
                ROUND(AVG(cps.composite_score)::numeric, 1) as avg_score
         FROM compliance_posture_snapshots cps
         JOIN engagements e ON cps.engagement_id = e.id
         WHERE e.org_id = $1
         GROUP BY DATE(cps.computed_at)
         ORDER BY day ASC
         LIMIT 90`,
        [session.user.orgId],
      );

      return NextResponse.json({
        average_composite_score: avgScore,
        total_engagements: engagements.length,
        engagements,
        severity_counts: severityCounts,
        trend: trendResult.rows || [],
        computed_at: new Date().toISOString(),
      });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Compliance posture API error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch compliance posture" },
      { status: 500 },
    );
  }
}
