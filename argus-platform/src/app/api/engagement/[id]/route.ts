import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: engagementId } = await params;
  log.api('GET', '/api/engagement/[id]', { engagementId });
  try {
    const session = await requireAuth();
    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    // Fetch engagement details
    const result = await pool.query(
      `SELECT e.*, lb.max_cycles, lb.max_depth,
              lb.current_cycles, lb.current_depth
       FROM engagements e
       LEFT JOIN loop_budgets lb ON e.id = lb.engagement_id
       WHERE e.id = $1`,
      [engagementId],
    );

    if (result.rows.length === 0) {
      log.apiEnd('GET', `/api/engagement/${engagementId}`, 404);
      return NextResponse.json(
        { error: "Engagement not found" },
        { status: 404 },
      );
    }

    log.apiEnd('GET', `/api/engagement/${engagementId}`, 200);
    return NextResponse.json({
      engagement: result.rows[0],
    });
  } catch (error: unknown) {
    log.error("Get engagement error:", error);
    const err = error as Error;

    const statusCode = err.message === "Unauthorized" ? 401 : err.message.startsWith("Forbidden") ? 403 : 500;
    log.apiEnd('GET', `/api/engagement/${engagementId || 'unknown'}`, statusCode);
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

    if (err.message.startsWith("ServiceUnavailable")) {
      return NextResponse.json(
        { error: "Authorization service unavailable" },
        { status: 503 },
      );
    }

    return NextResponse.json(
      { error: "Failed to fetch engagement" },
      { status: 500 },
    );
  }
}
