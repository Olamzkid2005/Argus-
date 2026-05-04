import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pool } from "@/lib/db";

/**
 * GET /api/engagement/[id]/activities
 *
 * Returns scanner activity log for an engagement.
 * Used by the dashboard "Live Operations" panel for DB-polling visibility
 * into what scanning tools are doing in real-time.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id: engagementId } = await params;

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    // Parse query params
    const { searchParams } = new URL(req.url);
    const limit = Math.min(
      parseInt(searchParams.get("limit") || "50", 10),
      200,
    );
    const since = searchParams.get("since");

    // Build query
    let query = `
      SELECT id, tool_name, activity, status, target, details, items_found, duration_ms, created_at
      FROM scanner_activities
      WHERE engagement_id = $1
    `;
    const queryParams: (string | number)[] = [engagementId];

    if (since) {
      query += ` AND created_at > $2`;
      queryParams.push(since);
    }

    query += ` ORDER BY created_at DESC LIMIT $${queryParams.length + 1}`;
    queryParams.push(limit);

    const result = await pool.query(query, queryParams);

    return NextResponse.json({
      engagement_id: engagementId,
      activities: result.rows,
      count: result.rows.length,
      timestamp: new Date().toISOString(),
    });
  } catch (error: unknown) {
    console.error("Get scanner activities error:", error);
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

    if (err.message.startsWith("ServiceUnavailable")) {
      return NextResponse.json(
        { error: "Authorization service unavailable" },
        { status: 503 },
      );
    }

    return NextResponse.json(
      { error: "Failed to fetch scanner activities" },
      { status: 500 },
    );
  }
}
