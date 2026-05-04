import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { v4 as uuidv4 } from "uuid";
import { pushJob } from "@/lib/redis";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

/**
 * POST /api/engagement/[id]/approve
 *
 * Approves findings and transitions engagement from awaiting_approval to scanning.
 * Pushes "scan" job to Redis queue.
 *
 * Requirements: 33.2, 33.3, 33.4
 */
export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: engagementId } = await params;
  log.api('POST', '/api/engagement/[id]/approve', { engagementId });
  try {
    const session = await requireAuth();

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    const client = await pool.connect();

    try {
      await client.query("BEGIN");

      // Get current engagement state with row lock
      const engagementResult = await client.query(
        `SELECT e.*, lb.max_cycles, lb.max_depth
         FROM engagements e
         LEFT JOIN loop_budgets lb ON e.id = lb.engagement_id
         WHERE e.id = $1
         FOR UPDATE OF e`,
        [engagementId],
      );

      if (engagementResult.rows.length === 0) {
        await client.query("ROLLBACK");
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 },
        );
      }

      const engagement = engagementResult.rows[0];

      // Verify engagement is in awaiting_approval state
      if (engagement.status !== "awaiting_approval") {
        await client.query("ROLLBACK");
        return NextResponse.json(
          {
            error: `Cannot approve engagement in ${engagement.status} state. Must be in awaiting_approval state.`,
          },
          { status: 400 },
        );
      }

      // Transition engagement to scanning state
      await client.query(
        `UPDATE engagements SET status = $1, updated_at = NOW() WHERE id = $2`,
        ["scanning", engagementId],
      );

      // Record state transition
      await client.query(
        `INSERT INTO engagement_states 
         (id, engagement_id, from_state, to_state, reason, created_at)
         VALUES ($1, $2, $3, $4, $5, NOW())`,
        [
          uuidv4(),
          engagementId,
          "awaiting_approval",
          "scanning",
          "User approved findings",
        ],
      );

      await client.query("COMMIT");

      // Push "scan" job to Redis queue
      const traceId = uuidv4();
      await pushJob({
        type: "scan",
        engagement_id: engagementId,
        target: engagement.target_url,
        budget: {
          max_cycles: engagement.max_cycles || 5,
          max_depth: engagement.max_depth || 3,
        },
        trace_id: traceId,
        created_at: new Date().toISOString(),
      });

      log.apiEnd('POST', `/api/engagement/${engagementId}/approve`, 200, { traceId });
      return NextResponse.json({
        message: "Engagement approved and scan job queued",
        engagement_id: engagementId,
        trace_id: traceId,
        status: "scanning",
      });
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  } catch (error: unknown) {
    log.error("Approve engagement error:", error);
    const err = error as Error;

    const statusCode = err.message === "Unauthorized" ? 401 : err.message.startsWith("Forbidden") ? 403 : 500;
    log.apiEnd('POST', `/api/engagement/${engagementId || 'unknown'}/approve`, statusCode);
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }

    return NextResponse.json(
      { error: "Failed to approve engagement" },
      { status: 500 },
    );
  }
}
