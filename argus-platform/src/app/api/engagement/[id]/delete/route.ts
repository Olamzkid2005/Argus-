// Delete engagement API route
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: engagementId } = await params;
  log.api('DELETE', '/api/engagement/[id]/delete', { engagementId });
  try {
    const session = await requireAuth();

    const client = await pool.connect();

    try {
      await client.query("BEGIN");

      // Check ownership
      const check = await client.query(
        "SELECT id, status FROM engagements WHERE id = $1 AND org_id = $2",
        [engagementId, session.user.orgId],
      );

      if (check.rowCount === 0) {
        await client.query("ROLLBACK");
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 },
        );
      }

      const currentStatus = check.rows[0]?.status;
      const activeStates = ["recon", "awaiting_approval", "scanning", "analyzing", "reporting"];
      if (activeStates.includes(currentStatus)) {
        await client.query("ROLLBACK");
        return NextResponse.json(
          { error: "Cannot delete engagement in progress. Stop it first." },
          { status: 400 },
        );
      }

      // Delete related records first (explicit deletion before engagement)
      console.log(`[DELETE ENGAGEMENT] Deleting related records for ${engagementId}`);
      await client.query("DELETE FROM findings WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM engagement_states WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM attack_paths WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM checkpoints WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM decision_snapshots WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM execution_logs WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM execution_failures WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM raw_outputs WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM scanner_activities WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM scope_violations WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM rate_limit_events WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM job_states WHERE engagement_id = $1", [engagementId]);
      await client.query("DELETE FROM loop_budgets WHERE engagement_id = $1", [engagementId]);
      console.log(`[DELETE ENGAGEMENT] Related records deleted, now deleting engagement`);

      // Finally delete the engagement
      const deleteResult = await client.query("DELETE FROM engagements WHERE id = $1", [
        engagementId,
      ]);

      await client.query("COMMIT");

      console.log(`[DELETE ENGAGEMENT] Deleted engagement ${engagementId}, rows affected: ${deleteResult.rowCount}`);

      log.apiEnd('DELETE', `/api/engagement/${engagementId}/delete`, 200, { deleted: deleteResult.rowCount });
      return NextResponse.json({ 
        success: true, 
        deleted: deleteResult.rowCount,
        engagementId 
      });
    } catch (error) {
      await client.query("ROLLBACK");
      log.error("Delete engagement transaction error:", error);
      throw error;
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Delete engagement outer error:", error);
    return NextResponse.json(
      { error: "Failed to delete engagement", details: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
