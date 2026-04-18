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
  { params }: { params: { id: string } }
) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const clusterId = searchParams.get("cluster_id");
    const engagementId = params.id;

    const client = await pool.connect();

    try {
      // Verify user has access to engagement
      const engagementResult = await client.query(
        "SELECT id, org_id FROM engagements WHERE id = $1",
        [engagementId]
      );

      if (engagementResult.rows.length === 0) {
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 }
        );
      }

      if (engagementResult.rows[0].org_id !== session.user.orgId) {
        return NextResponse.json(
          { error: "Forbidden" },
          { status: 403 }
        );
      }

      // Get explainability traces
      let query: string;
      let queryParams: (string | number | null)[];

      if (clusterId) {
        // Get trace for specific cluster
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
          WHERE t.cluster_id = $1
          ORDER BY t.created_at DESC
          LIMIT 1
        `;
        params = [clusterId];
      } else {
        // Get all traces for engagement
        // Note: This requires a way to link clusters to engagements
        // For now, we'll return all traces (in production, add engagement_id to clusters)
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
          ORDER BY t.created_at DESC
          LIMIT 100
        `;
        queryParams = [];
      }

      const result = await client.query(query, queryParams);

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
      { status: 500 }
    );
  }
}
