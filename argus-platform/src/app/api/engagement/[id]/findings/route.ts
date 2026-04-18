import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pool } from "@/lib/db";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const session = await requireAuth();
    const { id: engagementId } = await params;

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    // Parse query parameters for filtering and pagination
    const { searchParams } = new URL(req.url);
    const severity = searchParams.get("severity");
    const minConfidence = searchParams.get("minConfidence");
    const sourceTool = searchParams.get("sourceTool");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50", 10), 100);
    const offset = parseInt(searchParams.get("offset") || "0", 10);

    // Build query with filters
    let query = "SELECT * FROM findings WHERE engagement_id = $1";
    const queryParams: (string | number | string[])[] = [engagementId];
    let paramIndex = 2;

    if (severity) {
      const severities = severity.split(",");
      query += ` AND severity = ANY($${paramIndex})`;
      queryParams.push(severities);
      paramIndex++;
    }

    if (minConfidence) {
      query += ` AND confidence >= $${paramIndex}`;
      queryParams.push(parseFloat(minConfidence));
      paramIndex++;
    }

    if (sourceTool) {
      const tools = sourceTool.split(",");
      query += ` AND source_tool = ANY($${paramIndex})`;
      queryParams.push(tools);
      paramIndex++;
    }

    query += " ORDER BY severity DESC, confidence DESC, created_at DESC";

    // Get total count
    let countQuery = query.replace("SELECT *", "SELECT COUNT(*)");
    countQuery = countQuery.split("ORDER BY")[0];
    const countResult = await pool.query(countQuery, queryParams.slice(0, paramIndex - 1));
    const total = parseInt(countResult.rows[0].count, 10);

    // Apply pagination
    query += ` LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
    queryParams.push(limit, offset);

    const result = await pool.query(query, queryParams);

    const hasMore = offset + result.rows.length < total;

    return NextResponse.json({
      findings: result.rows,
      total,
      limit,
      offset,
      hasMore,
    });
  } catch (error: unknown) {
    console.error("Get findings error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: err.message }, { status: 403 });
    }
    
    return NextResponse.json(
      { error: "Failed to fetch findings" },
      { status: 500 }
    );
  }
}
