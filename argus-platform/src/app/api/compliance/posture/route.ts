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
        // H-v3-01: Verify the engagement belongs to the user's org before
        // returning compliance data — prevents cross-tenant data leakage.
        const engagementCheck = await client.query(
          `SELECT id FROM engagements WHERE id = $1 AND org_id = $2`,
          [engagementId, session.user.orgId],
        );
        if (engagementCheck.rows.length === 0) {
          return NextResponse.json(
            { error: "Engagement not found or access denied" },
            { status: 404 },
          );
        }

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

      const engagements = (orgResult.rows || []).map((r: Record<string, unknown>) => ({
        ...r,
        framework_scores: typeof r.framework_scores === "string"
          ? JSON.parse(r.framework_scores as string)
          : r.framework_scores,
      }));
      let avgScore = 100.0;
      if (engagements.length > 0) {
        const total = engagements.reduce((sum, r) => sum + parseFloat(r.composite_score || 100), 0);
        avgScore = Math.round((total / engagements.length) * 10) / 10;
      }

      // Aggregate per-framework scores across all engagements
      const frameworkTotals: Record<string, { score: number; count: number }> = {};
      for (const eng of engagements) {
        const fw = eng.framework_scores as Record<string, { score: number }> | undefined;
        if (!fw) continue;
        for (const [fwName, fwData] of Object.entries(fw)) {
          if (!frameworkTotals[fwName]) frameworkTotals[fwName] = { score: 0, count: 0 };
          frameworkTotals[fwName].score += Number(fwData.score) || 0;
          frameworkTotals[fwName].count += 1;
        }
      }
      const frameworkAverages: Record<string, number> = {};
      for (const [fwName, data] of Object.entries(frameworkTotals)) {
        frameworkAverages[fwName] = Math.round((data.score / data.count) * 10) / 10;
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
        framework_averages: frameworkAverages,
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
