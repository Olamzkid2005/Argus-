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

    // Fetch engagement details
    const result = await pool.query(
      `SELECT e.*, lb.max_cycles, lb.max_depth, lb.max_cost, 
              lb.current_cycles, lb.current_depth, lb.current_cost
       FROM engagements e
       LEFT JOIN loop_budgets lb ON e.id = lb.engagement_id
       WHERE e.id = $1`,
      [engagementId]
    );

    if (result.rows.length === 0) {
      return NextResponse.json(
        { error: "Engagement not found" },
        { status: 404 }
      );
    }

    return NextResponse.json({
      engagement: result.rows[0],
    });
  } catch (error: any) {
    console.error("Get engagement error:", error);
    
    if (error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    if (error.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: error.message }, { status: 403 });
    }
    
    return NextResponse.json(
      { error: "Failed to fetch engagement" },
      { status: 500 }
    );
  }
}
