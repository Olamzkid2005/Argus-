import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

/**
 * GET /api/compliance-posture
 *
 * Returns org-level aggregate compliance posture summary across all engagements.
 * Optional query params: engagement_id to filter for a specific engagement.
 */
export async function GET(req: Request) {
  try {
    const session = await requireAuth();
    const orgId = session.user.orgId;

    const { searchParams } = new URL(req.url);
    const engagementId = searchParams.get("engagement_id");

    // If a specific engagement is requested, redirect to the engagement-specific endpoint
    if (engagementId) {
      const latestResult = await pool.query(
        `SELECT id, engagement_id, composite_score, framework_scores,
                total_findings, trend, previous_score, computed_at
         FROM compliance_posture_snapshots
         WHERE engagement_id = $1
         ORDER BY computed_at DESC
         LIMIT 1`,
        [engagementId],
      );

      const historyResult = await pool.query(
        `SELECT id, engagement_id, composite_score, framework_scores,
                total_findings, trend, computed_at
         FROM compliance_posture_snapshots
         WHERE engagement_id = $1
         ORDER BY computed_at DESC
         LIMIT 30`,
        [engagementId],
      );

      return NextResponse.json({
        engagement_id: engagementId,
        latest: latestResult.rows[0]
          ? {
              ...latestResult.rows[0],
              framework_scores:
                typeof latestResult.rows[0].framework_scores === "string"
                  ? JSON.parse(latestResult.rows[0].framework_scores)
                  : latestResult.rows[0].framework_scores,
              computed_at: latestResult.rows[0].computed_at
                ? new Date(
                    latestResult.rows[0].computed_at,
                  ).toISOString()
                : null,
            }
          : null,
        history: historyResult.rows.map((row: Record<string, unknown>) => ({
          ...row,
          framework_scores:
            typeof row.framework_scores === "string"
              ? JSON.parse(row.framework_scores as string)
              : row.framework_scores,
          computed_at: row.computed_at
            ? new Date(row.computed_at as string).toISOString()
            : null,
        })),
      });
    }

    // Compute org-level aggregate summary
    // Get latest snapshot per engagement for this org
    const summaryResult = await pool.query(
      `SELECT DISTINCT ON (cps.engagement_id)
              cps.engagement_id,
              e.target_url,
              e.status AS engagement_status,
              cps.composite_score,
              cps.total_findings,
              cps.trend,
              cps.computed_at
       FROM compliance_posture_snapshots cps
       JOIN engagements e ON cps.engagement_id = e.id
       WHERE e.org_id = $1
       ORDER BY cps.engagement_id, cps.computed_at DESC`,
      [orgId],
    );

    const engagements = summaryResult.rows.map(
      (row: Record<string, unknown>) => ({
        ...row,
        computed_at: row.computed_at
          ? new Date(row.computed_at as string).toISOString()
          : null,
      }),
    );

    // Compute average
    let totalScore = 0;
    for (const eng of engagements) {
      totalScore += Number(eng.composite_score || 0);
    }
    const averageCompositeScore =
      engagements.length > 0
        ? Math.round((totalScore / engagements.length) * 10) / 10
        : 100.0;

    // Get org-level finding stats
    const findingStatsResult = await pool.query(
      `SELECT
         COUNT(*) AS total,
         COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical,
         COUNT(*) FILTER (WHERE severity = 'HIGH') AS high,
         COUNT(*) FILTER (WHERE severity = 'MEDIUM') AS medium
       FROM findings f
       JOIN engagements e ON f.engagement_id = e.id
       WHERE e.org_id = $1`,
      [orgId],
    );

    const findingStats = findingStatsResult.rows[0] || {
      total: 0,
      critical: 0,
      high: 0,
      medium: 0,
    };

    return NextResponse.json({
      org_id: orgId,
      average_composite_score: averageCompositeScore,
      total_engagements: engagements.length,
      total_findings: parseInt(String(findingStats.total ?? "0"), 10),
      critical_findings: parseInt(String(findingStats.critical ?? "0"), 10),
      high_findings: parseInt(String(findingStats.high ?? "0"), 10),
      medium_findings: parseInt(String(findingStats.medium ?? "0"), 10),
      engagements: engagements,
      worst_performers: [...engagements]
        .sort(
          (a: Record<string, unknown>, b: Record<string, unknown>) =>
            Number(a.composite_score || 100) -
            Number(b.composite_score || 100),
        )
        .slice(0, 5),
      computed_at: new Date().toISOString(),
    });
  } catch (error: unknown) {
    console.error("Get compliance posture error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch compliance posture summary" },
      { status: 500 },
    );
  }
}
