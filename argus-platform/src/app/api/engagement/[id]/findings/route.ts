import { NextResponse } from "next/server";
import { Pool } from "pg";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export async function GET(
  req: Request,
  { params }: { params: { id: string } }
) {
  try {
    const session = await requireAuth();
    const engagementId = params.id;

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    // Parse query parameters for filtering
    const { searchParams } = new URL(req.url);
    const severity = searchParams.get("severity");
    const minConfidence = searchParams.get("minConfidence");
    const sourceTool = searchParams.get("sourceTool");

    // Build query with filters
    let query = "SELECT * FROM findings WHERE engagement_id = $1";
    const params: any[] = [engagementId];
    let paramIndex = 2;

    if (severity) {
      const severities = severity.split(",");
      query += ` AND severity = ANY($${paramIndex})`;
      params.push(severities);
      paramIndex++;
    }

    if (minConfidence) {
      query += ` AND confidence >= $${paramIndex}`;
      params.push(parseFloat(minConfidence));
      paramIndex++;
    }

    if (sourceTool) {
      const tools = sourceTool.split(",");
      query += ` AND source_tool = ANY($${paramIndex})`;
      params.push(tools);
      paramIndex++;
    }

    query += " ORDER BY severity DESC, confidence DESC, created_at DESC";

    const result = await pool.query(query, params);

    return NextResponse.json({
      findings: result.rows,
      count: result.rows.length,
    });
  } catch (error: any) {
    console.error("Get findings error:", error);
    
    if (error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    if (error.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: error.message }, { status: 403 });
    }
    
    return NextResponse.json(
      { error: "Failed to fetch findings" },
      { status: 500 }
    );
  }
}
