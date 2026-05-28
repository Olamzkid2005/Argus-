import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pool } from "@/lib/db";

/**
 * GET /api/engagement/[id]/compliance-posture
 *
 * Returns the current compliance posture for an engagement.
 * Optional query params: history=true to include snapshot history.
 */
export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id: engagementId } = await params;
    await requireEngagementAccess(session, engagementId);

    const { searchParams } = new URL(req.url);
    const includeHistory = searchParams.get("history") === "true";
    const limit = Math.min(
      parseInt(searchParams.get("limit") || "20", 10),
      50,
    );

    // Fetch latest snapshot
    const latestResult = await pool.query(
      `SELECT id, engagement_id, composite_score, framework_scores,
              total_findings, trend, previous_score, computed_at
       FROM compliance_posture_snapshots
       WHERE engagement_id = $1
       ORDER BY computed_at DESC
       LIMIT 1`,
      [engagementId],
    );

    let latest = null;
    if (latestResult.rows.length > 0) {
      latest = latestResult.rows[0];
      if (typeof latest.framework_scores === "string") {
        latest.framework_scores = JSON.parse(latest.framework_scores);
      }
      if (latest.computed_at) {
        latest.computed_at = new Date(latest.computed_at).toISOString();
      }
    }

    // M-v3-09: Return null when no snapshot exists — a perfect 100 score is misleading
    // when the engagement may have critical unverified findings.
    // Frontend should show "Not yet assessed" instead.
    if (!latest) {
      return NextResponse.json({ latest: null, history: [] });
    }

    // Fetch history if requested
    let history: unknown[] = [];
    if (includeHistory) {
      const historyResult = await pool.query(
        `SELECT id, engagement_id, composite_score, framework_scores,
                total_findings, trend, computed_at
         FROM compliance_posture_snapshots
         WHERE engagement_id = $1
         ORDER BY computed_at DESC
         LIMIT $2`,
        [engagementId, limit],
      );
      history = historyResult.rows.map((row: Record<string, unknown>) => {
        const r = { ...row };
        if (typeof r.framework_scores === "string") {
          r.framework_scores = JSON.parse(r.framework_scores as string);
        }
        if (r.computed_at) {
          r.computed_at = new Date(r.computed_at as string).toISOString();
        }
        return r;
      });
    }

    return NextResponse.json({
      latest,
      history: includeHistory ? history : undefined,
      engagement_id: engagementId,
    });
  } catch (error: unknown) {
    console.error("Get compliance posture error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }
    if (err.message.startsWith("NotFound")) {
      return NextResponse.json(
        { error: "Engagement not found" },
        { status: 404 },
      );
    }
    return NextResponse.json(
      { error: "Failed to fetch compliance posture" },
      { status: 500 },
    );
  }
}
