import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { v4 as uuidv4 } from "uuid";
import { pushJob } from "@/lib/redis";
import { pool } from "@/lib/db";

/**
 * POST /api/engagement/[id]/rescan
 *
 * Clones an existing engagement and starts a fresh scan with the same target.
 * Creates a new engagement with the same target_url, scan_type, and settings,
 * then pushes the appropriate scan job.
 */
export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id: engagementId } = await params;

    // Verify user has access to the source engagement
    await requireEngagementAccess(session, engagementId);

    const client = await pool.connect();

    try {
      // Fetch existing engagement details
      const sourceResult = await client.query(
        `SELECT target_url, authorization_proof, authorized_scope,
                scan_type, scan_aggressiveness, rate_limit_config
         FROM engagements WHERE id = $1`,
        [engagementId],
      );

      if (sourceResult.rows.length === 0) {
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 },
        );
      }

      const source = sourceResult.rows[0];

      await client.query("BEGIN");

      // Create new engagement with same target and settings
      const newEngagementId = uuidv4();
      const engagementResult = await client.query(
        `INSERT INTO engagements
         (id, org_id, target_url, authorization_proof, authorized_scope, status, created_by, rate_limit_config, scan_type, scan_aggressiveness, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
         RETURNING *`,
        [
          newEngagementId,
          session.user.orgId,
          source.target_url,
          source.authorization_proof,
          source.authorized_scope,
          "created",
          session.user.id,
          source.rate_limit_config,
          source.scan_type || "url",
          source.scan_aggressiveness || "default",
        ],
      );

      // Initialize loop budget with defaults
      await client.query(
        `INSERT INTO loop_budgets
         (id, engagement_id, max_cycles, max_depth, max_cost, current_cycles, current_depth, current_cost, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())`,
        [uuidv4(), newEngagementId, 5, 3, 0.5, 0, 0, 0.0],
      );

      // Record initial state transition
      await client.query(
        `INSERT INTO engagement_states
         (id, engagement_id, from_state, to_state, reason, created_at)
         VALUES ($1, $2, $3, $4, $5, NOW())`,
        [uuidv4(), newEngagementId, null, "created", "Rescan of engagement " + engagementId],
      );

      await client.query("COMMIT");

      // Push scan job
      const traceId = uuidv4();
      const scanType = source.scan_type || "url";

      try {
        if (scanType === "repo") {
          await pushJob({
            type: "repo_scan",
            engagement_id: newEngagementId,
            target: source.target_url,
            repo_url: source.target_url,
            budget: { max_cycles: 5, max_depth: 3, max_cost: 0.5 },
            aggressiveness: source.scan_aggressiveness || "default",
            trace_id: traceId,
            created_at: new Date().toISOString(),
          });
        } else {
          await pushJob({
            type: "recon",
            engagement_id: newEngagementId,
            target: source.target_url,
            budget: { max_cycles: 5, max_depth: 3, max_cost: 0.5 },
            aggressiveness: source.scan_aggressiveness || "default",
            trace_id: traceId,
            created_at: new Date().toISOString(),
          });
        }
      } catch (jobError) {
        // Rollback if job push fails
        await client.query("DELETE FROM engagements WHERE id = $1", [newEngagementId]);
        throw new Error(
          `Job dispatch failed: ${jobError instanceof Error ? jobError.message : "unknown error"}`,
        );
      }

      return NextResponse.json({
        engagement: engagementResult.rows[0],
        trace_id: traceId,
      });
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  } catch (error: unknown) {
    console.error("Rescan error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: err.message }, { status: 403 });
    }

    return NextResponse.json(
      { error: "Failed to rescan engagement" },
      { status: 500 },
    );
  }
}
