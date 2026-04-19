// Rate limiting configuration API route
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const engagementId = searchParams.get("engagement_id");

    if (!engagementId) {
      return NextResponse.json(
        { error: "engagement_id is required" },
        { status: 400 },
      );
    }

    const client = await pool.connect();

    try {
      const result = await client.query(
        `SELECT rate_limit_config FROM engagements WHERE id = $1 AND org_id = $2`,
        [engagementId, session.user.orgId],
      );

      if (result.rows.length === 0) {
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 },
        );
      }

      const config = result.rows[0].rate_limit_config || {
        requestsPerSecond: 5,
        concurrentRequests: 2,
        respectRobotsTxt: true,
        adaptiveSlowdown: true,
      };

      return NextResponse.json(config);
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Rate limit config error:", error);
    return NextResponse.json(
      { error: "Failed to fetch rate limit configuration" },
      { status: 500 },
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { engagementId, config } = body;

    if (!engagementId) {
      return NextResponse.json(
        { error: "engagement_id is required" },
        { status: 400 },
      );
    }

    // Validate config
    const {
      requestsPerSecond,
      concurrentRequests,
      respectRobotsTxt,
      adaptiveSlowdown,
    } = config;

    if (
      requestsPerSecond &&
      (requestsPerSecond < 1 || requestsPerSecond > 20)
    ) {
      return NextResponse.json(
        { error: "requestsPerSecond must be between 1 and 20" },
        { status: 400 },
      );
    }

    if (
      concurrentRequests &&
      (concurrentRequests < 1 || concurrentRequests > 5)
    ) {
      return NextResponse.json(
        { error: "concurrentRequests must be between 1 and 5" },
        { status: 400 },
      );
    }

    const client = await pool.connect();

    try {
      await client.query(
        `UPDATE engagements SET rate_limit_config = $1, updated_at = NOW() WHERE id = $2 AND org_id = $3`,
        [config, engagementId, session.user.orgId],
      );

      return NextResponse.json({ success: true, config });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Rate limit update error:", error);
    return NextResponse.json(
      { error: "Failed to update rate limit configuration" },
      { status: 500 },
    );
  }
}
