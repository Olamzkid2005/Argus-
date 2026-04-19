import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pool } from "@/lib/db";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id: engagementId } = await params;

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    // Fetch engagement details
    const result = await pool.query(
      `SELECT e.*, lb.max_cycles, lb.max_depth, lb.max_cost, 
              lb.current_cycles, lb.current_depth, lb.current_cost
       FROM engagements e
       LEFT JOIN loop_budgets lb ON e.id = lb.engagement_id
       WHERE e.id = $1`,
      [engagementId],
    );

    if (result.rows.length === 0) {
      return NextResponse.json(
        { error: "Engagement not found" },
        { status: 404 },
      );
    }

    return NextResponse.json({
      engagement: result.rows[0],
    });
  } catch (error: unknown) {
    console.error("Get engagement error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: err.message }, { status: 403 });
    }

    return NextResponse.json(
      { error: "Failed to fetch engagement" },
      { status: 500 },
    );
  }
}
