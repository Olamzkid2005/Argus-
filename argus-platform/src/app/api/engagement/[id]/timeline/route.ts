import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pool } from "@/lib/db";

/**
 * GET /api/engagement/[id]/timeline
 *
 * Returns execution timeline for an engagement.
 *
 * Requirements: 21.3, 21.4, 21.5
 */

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id: engagementId } = await params;

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    // Parse query parameters for pagination
    const { searchParams } = new URL(req.url);
    const limit = Math.min(
      parseInt(searchParams.get("limit") || "50", 10),
      100,
    );
    const offset = parseInt(searchParams.get("offset") || "0", 10);

    // Query execution spans ordered by timestamp
    // Note: execution_spans doesn't have engagement_id, so we join through execution_logs
    const baseQuery = `
      SELECT DISTINCT
        es.id,
        es.trace_id,
        es.span_name,
        es.duration_ms,
        es.created_at
      FROM execution_spans es
      INNER JOIN execution_logs el ON es.trace_id = el.trace_id
      WHERE el.engagement_id = $1
    `;

    // Get total count
    const countQuery = baseQuery
      .replace("SELECT DISTINCT es.id,", "SELECT COUNT(DISTINCT es.id)")
      .replace(
        "SELECT DISTINCT es.trace_id,",
        "SELECT COUNT(DISTINCT es.trace_id),",
      );
    const countResult = await pool.query(countQuery, [engagementId]);
    const total = parseInt(countResult.rows[0].count, 10);

    // Apply ordering and pagination
    const query = baseQuery + " ORDER BY es.created_at ASC LIMIT $2 OFFSET $3";
    const result = await pool.query(query, [engagementId, limit, offset]);

    const hasMore = offset + result.rows.length < total;

    return NextResponse.json({
      spans: result.rows,
      total,
      limit,
      offset,
      hasMore,
    });
  } catch (error: unknown) {
    console.error("Get timeline error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: err.message }, { status: 403 });
    }

    return NextResponse.json(
      { error: "Failed to fetch timeline" },
      { status: 500 },
    );
  }
}
