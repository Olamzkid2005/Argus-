import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { v4 as uuidv4 } from "uuid";
import { pushJob } from "@/lib/redis";
import { pool } from "@/lib/db";

export async function POST(req: Request) {
  try {
    const session = await requireAuth();
    const body = await req.json();

    const { targetUrl, authorization, authorizedScope, rateLimitConfig } = body;

    // Validate authorized_scope has at least one domain or IP
    if (
      (!authorizedScope.domains || authorizedScope.domains.length === 0) &&
      (!authorizedScope.ipRanges || authorizedScope.ipRanges.length === 0)
    ) {
      return NextResponse.json(
        { error: "authorized_scope must contain at least one domain or IP range" },
        { status: 400 }
      );
    }

    // Validate rate limit configuration if provided
    if (rateLimitConfig) {
      const { requests_per_second, concurrent_requests } = rateLimitConfig;
      
      if (requests_per_second !== undefined) {
        if (typeof requests_per_second !== 'number' || requests_per_second < 1 || requests_per_second > 20) {
          return NextResponse.json(
            { error: "requests_per_second must be between 1 and 20" },
            { status: 400 }
          );
        }
      }
      
      if (concurrent_requests !== undefined) {
        if (typeof concurrent_requests !== 'number' || concurrent_requests < 1 || concurrent_requests > 5) {
          return NextResponse.json(
            { error: "concurrent_requests must be between 1 and 5" },
            { status: 400 }
          );
        }
      }
    }

    const client = await pool.connect();
    
    try {
      await client.query("BEGIN");

      // Create engagement
      const engagementId = uuidv4();
      const engagementResult = await client.query(
        `INSERT INTO engagements 
         (id, org_id, target_url, authorization, authorized_scope, status, created_by, rate_limit_config, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
         RETURNING *`,
        [
          engagementId,
          session.user.orgId,
          targetUrl,
          authorization,
          JSON.stringify(authorizedScope),
          "created",
          session.user.id,
          rateLimitConfig ? JSON.stringify(rateLimitConfig) : null,
        ]
      );

      // Initialize loop budget with defaults
      await client.query(
        `INSERT INTO loop_budgets 
         (id, engagement_id, max_cycles, max_depth, max_cost, current_cycles, current_depth, current_cost, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())`,
        [uuidv4(), engagementId, 5, 3, 0.50, 0, 0, 0.0]
      );

      // Record initial state transition
      await client.query(
        `INSERT INTO engagement_states 
         (id, engagement_id, from_state, to_state, reason, created_at)
         VALUES ($1, $2, $3, $4, $5, NOW())`,
        [uuidv4(), engagementId, null, "created", "Engagement created"]
      );

      await client.query("COMMIT");

      // Push "recon" job to Redis queue
      const traceId = uuidv4();
      await pushJob({
        type: "recon",
        engagement_id: engagementId,
        target: targetUrl,
        budget: {
          max_cycles: 5,
          max_depth: 3,
          max_cost: 0.50,
        },
        trace_id: traceId,
        created_at: new Date().toISOString(),
      });

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
    console.error("Create engagement error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    return NextResponse.json(
      { error: "Failed to create engagement" },
      { status: 500 }
    );
  }
}
