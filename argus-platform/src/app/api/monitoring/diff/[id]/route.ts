// GET /api/monitoring/diff/[engagement_id]
// Returns the diff summary between this engagement and the previous one for the same target
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { createErrorResponse, ErrorCodes } from "@/lib/api/errors";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const [session, { id }] = await Promise.all([
      requireAuth(),
      params,
    ]);

    const client = await pool.connect();
    try {
      const engResult = await client.query(
        "SELECT target_url, org_id FROM engagements WHERE id = $1",
        [id],
      );
      if (engResult.rows.length === 0) {
        return createErrorResponse(
          "Engagement not found",
          ErrorCodes.NOT_FOUND,
          undefined,
          404,
        );
      }

      const { target_url, org_id } = engResult.rows[0];
      const domain = new URL(target_url).hostname;

      const diffResult = await client.query(
        `SELECT last_diff_summary FROM target_profiles
         WHERE org_id = $1 AND target_domain = $2`,
        [org_id, domain],
      );

      if (
        diffResult.rows.length === 0 ||
        !diffResult.rows[0].last_diff_summary
      ) {
        return NextResponse.json({
          new: [],
          fixed: [],
          regressed: [],
          persistent: [],
          severity_changed: [],
          summary: {
            action_required: false,
            new_count: 0,
            fixed_count: 0,
            regressed_count: 0,
            total_current: 0,
            total_previous: 0,
          },
        });
      }

      return NextResponse.json(diffResult.rows[0].last_diff_summary);
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Diff API error:", error);
    return createErrorResponse(
      "Failed to fetch diff",
      ErrorCodes.INTERNAL_ERROR,
      undefined,
      500,
    );
  }
}
