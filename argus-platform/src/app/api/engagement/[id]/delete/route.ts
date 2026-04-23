// Delete engagement API route
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    const session = await requireAuth();
    const engagementId = params.id;

    const client = await pool.connect();

    try {
      // Check ownership
      const check = await client.query(
        "SELECT id FROM engagements WHERE id = $1 AND org_id = $2",
        [engagementId, session.user.orgId],
      );

      if (check.rowCount === 0) {
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 },
        );
      }

      // Allow deletion of non-active engagements
      const statusCheck = await client.query(
        "SELECT status FROM engagements WHERE id = $1",
        [engagementId],
      );

      const currentStatus = statusCheck.rows[0]?.status;
      const activeStates = ["recon", "awaiting_approval", "scanning", "analyzing", "reporting"];
      if (activeStates.includes(currentStatus)) {
        return NextResponse.json(
          { error: "Cannot delete engagement in progress. Stop it first." },
          { status: 400 },
        );
      }

      // Delete engagement (cascades to findings, states, etc.)
      await client.query("DELETE FROM engagements WHERE id = $1", [
        engagementId,
      ]);

      return NextResponse.json({ success: true });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Delete engagement error:", error);
    return NextResponse.json(
      { error: "Failed to delete engagement" },
      { status: 500 },
    );
  }
}
