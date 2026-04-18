import { NextResponse } from "next/server";
import { Pool } from "pg";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";

/**
 * GET /api/engagement/[id]/timeline
 * 
 * Returns execution timeline for an engagement.
 * 
 * Requirements: 21.3, 21.4, 21.5
 */

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const session = await requireAuth();
    const { id: engagementId } = await params;

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    // Query execution spans ordered by timestamp
    // Note: execution_spans doesn't have engagement_id, so we join through execution_logs
    const query = `
      SELECT DISTINCT
        es.id,
        es.trace_id,
        es.span_name,
        es.duration_ms,
        es.created_at
      FROM execution_spans es
      INNER JOIN execution_logs el ON es.trace_id = el.trace_id
      WHERE el.engagement_id = $1
      ORDER BY es.created_at ASC
    `;

    const result = await pool.query(query, [engagementId]);

    return NextResponse.json({
      spans: result.rows,
      count: result.rows.length,
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
      { status: 500 }
    );
  }
}
