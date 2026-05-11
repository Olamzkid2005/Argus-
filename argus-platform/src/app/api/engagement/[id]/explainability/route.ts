import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

/**
 * GET /api/engagement/[id]/explainability
 *
 * Get explainability traces for an engagement's vulnerability clusters.
 *
 * Query parameters:
 * - cluster_id: Optional cluster ID to filter by
 *
 * Requirements: 24.3, 24.4
 */
export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const clusterId = searchParams.get("cluster_id");
    const { id: engagementId } = await params;

    const client = await pool.connect();

    try {
      // Verify user has access to engagement
      const engagementResult = await client.query(
        "SELECT id, org_id FROM engagements WHERE id = $1",
        [engagementId],
      );

      if (engagementResult.rows.length === 0) {
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 },
        );
      }

      if (engagementResult.rows[0].org_id !== session.user.orgId) {
        return NextResponse.json({ error: "Forbidden" }, { status: 403 });
      }

      // Get explainability traces
      let query: string;
      let sqlParams: (string | number | null)[];

      if (clusterId) {
        // Get trace for specific cluster, scoped to engagement's org
        query = `
          SELECT 
            t.id,
            t.cluster_id,
            t.trace_data,
            t.created_at,
            t.explanation,
            e.type as finding_type,
            e.severity
          FROM ai_explainability_traces t
          LEFT JOIN findings e ON e.id = t.cluster_id
          WHERE t.cluster_id = $1 AND e.engagement_id = $2
          ORDER BY t.created_at DESC
          LIMIT 1
        `;
        sqlParams = [clusterId, engagementId];
      } else {
        // Get all traces for this engagement's org only
        query = `
          SELECT 
            t.id,
            t.cluster_id,
            t.trace_data,
            t.created_at,
            e.explanation,
            e.model_version,
            e.token_count
          FROM ai_explainability_traces t
          LEFT JOIN ai_explanations e ON e.cluster_id = t.cluster_id
          INNER JOIN findings f ON f.id = t.cluster_id
          WHERE f.engagement_id = $1
          ORDER BY t.created_at DESC
          LIMIT 100
        `;
        sqlParams = [engagementId];
      }

      const result = await client.query(query, sqlParams);

      // Parse trace_data JSON if it's a string
      const traces = result.rows.map((row) => ({
        ...row,
        trace_data:
          typeof row.trace_data === "string"
            ? JSON.parse(row.trace_data)
            : row.trace_data,
      }));

      return NextResponse.json({
        traces,
        count: traces.length,
      });
    } finally {
      client.release();
    }
  } catch (error: unknown) {
    console.error("Get explainability traces error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    return NextResponse.json(
      { error: "Failed to get explainability traces" },
      { status: 500 },
    );
  }
}
