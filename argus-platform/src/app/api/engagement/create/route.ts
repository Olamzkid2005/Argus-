import { NextRequest, NextResponse } from "next/server";
import { createErrorResponse, ErrorCodes } from "@/lib/api/errors";
import { requireAuth } from "@/lib/session";
import { v4 as uuidv4 } from "uuid";
import { pushJob, checkIdempotency, setAPIIdempotencyResult, generateAPIIdempotencyKey } from "@/lib/redis";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";
import { createRateLimit } from "@/lib/rate-limiter";

// Max 10 engagement creations per hour per user
const engagementRateLimit = createRateLimit({
  windowMs: 3600000, // 1 hour
  maxRequests: 10,
});

export async function POST(req: NextRequest) {
  log.api('POST', '/api/engagement/create');
  try {
    // Apply rate limiting before anything else
    const rateLimitResponse = await engagementRateLimit(req);
    if (rateLimitResponse) {
      return rateLimitResponse;
    }

    const session = await requireAuth();
    const body = await req.json();

    // Check idempotency - return cached response if duplicate request
    const idempotencyKey = req.headers.get("x-idempotency-key");
    const cachedResult = await checkIdempotency(
      session.user.id,
      "/api/engagement/create",
      body,
      idempotencyKey || undefined
    );

    if (cachedResult) {
      return NextResponse.json(JSON.parse(cachedResult), { status: 200 });
    }

    const {
      targetUrl,
      authorization,
      authorizedScope,
      rateLimitConfig,
      scanType,
      scanAggressiveness,
      agentMode,
      scanMode,
      bugBounty,
    } = body;

    // Default authorization proof if not provided (NOT NULL column)
    const authorizationProof = authorization || "authorized_testing";

    // Default to "url" scan type if not specified
    const effectiveScanType = scanType || "url";

    // Validate authorized_scope - for repo scans, this can be empty
    if (
      effectiveScanType === "url" &&
      (!authorizedScope || !authorizedScope.domains || authorizedScope.domains.length === 0) &&
      (!authorizedScope || !authorizedScope.ipRanges || authorizedScope.ipRanges.length === 0)
    ) {
      return createErrorResponse(
        "authorized_scope must contain at least one domain or IP range",
        ErrorCodes.VALIDATION_ERROR,
        undefined,
        400,
      );
    }

    if (!targetUrl) {
      return createErrorResponse("targetUrl is required", ErrorCodes.VALIDATION_ERROR, undefined, 400);
    }

    // Validate rate limit configuration if provided
    if (rateLimitConfig) {
      const { requests_per_second, concurrent_requests } = rateLimitConfig;

      if (requests_per_second !== undefined) {
        if (
          typeof requests_per_second !== "number" ||
          requests_per_second < 1 ||
          requests_per_second > 20
        ) {
          return createErrorResponse(
            "requests_per_second must be between 1 and 20",
            ErrorCodes.VALIDATION_ERROR,
            undefined,
            400,
          );
        }
      }

      if (concurrent_requests !== undefined) {
        if (
          typeof concurrent_requests !== "number" ||
          concurrent_requests < 1 ||
          concurrent_requests > 5
        ) {
          return createErrorResponse(
            "concurrent_requests must be between 1 and 5",
            ErrorCodes.VALIDATION_ERROR,
            undefined,
            400,
          );
        }
      }
    }

    const client = await pool.connect();

    try {
      await client.query("BEGIN");

      // Create engagement
      const engagementId = uuidv4();
      const effectiveAggressiveness = scanAggressiveness || "default";
      const effectiveAgentMode = agentMode === true;
      const engagementResult = await client.query(
        `INSERT INTO engagements 
         (id, org_id, target_url, authorization_proof, authorized_scope, status, created_by, rate_limit_config, scan_type, scan_aggressiveness, agent_mode, scan_mode, bug_bounty_mode, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
         RETURNING *`,
        [
          engagementId,
          session.user.orgId,
          targetUrl,
          authorizationProof,
          JSON.stringify(authorizedScope),
          "created",
          session.user.id,
          rateLimitConfig ? JSON.stringify(rateLimitConfig) : null,
          effectiveScanType,
          effectiveAggressiveness,
          effectiveAgentMode,
          scanMode || "agent",
          bugBounty === true,
        ],
      );

      // Initialize loop budget with defaults
      await client.query(
        `INSERT INTO loop_budgets 
         (id, engagement_id, max_cycles, max_depth, current_cycles, current_depth, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, NOW())`,
        [uuidv4(), engagementId, 5, 3, 0, 0],
      );

      // Record initial state transition
      await client.query(
        `INSERT INTO engagement_states 
         (id, engagement_id, from_state, to_state, reason, created_at)
         VALUES ($1, $2, $3, $4, $5, NOW())`,
        [uuidv4(), engagementId, null, "created", "Engagement created"],
      );

      // NOTE: Auto-clear removed — this was destroying ALL historical findings
      // for the entire org on every engagement creation, causing data loss.
      // Each engagement starts with no findings naturally — no cleanup needed.

      await client.query("COMMIT");

      // Push job to Redis queue based on scan type
      const traceId = uuidv4();
      let jobPushed = false;

      try {
        if (effectiveScanType === "repo") {
          // Repository scan - clone repo and run Semgrep
          await pushJob({
            type: "repo_scan",
            engagement_id: engagementId,
            target: targetUrl,
            repo_url: targetUrl,
            budget: {
              max_cycles: 5,
              max_depth: 3,
            },
            aggressiveness: effectiveAggressiveness,
            agent_mode: effectiveAgentMode,
            scan_mode: scanMode || "agent",
            bug_bounty_mode: bugBounty === true,
            trace_id: traceId,
            created_at: new Date().toISOString(),
          });
        } else {
          // Web app scan - run reconnaissance
          await pushJob({
            type: "recon",
            engagement_id: engagementId,
            target: targetUrl,
            budget: {
              max_cycles: 5,
              max_depth: 3,
            },
            aggressiveness: effectiveAggressiveness,
            agent_mode: effectiveAgentMode,
            scan_mode: scanMode || "agent",
            bug_bounty_mode: bugBounty === true,
            trace_id: traceId,
            created_at: new Date().toISOString(),
          });
        }
        jobPushed = true;
      } catch (jobError) {
        console.error("Failed to push job:", jobError);
        // Rollback: delete engagement + related rows if job push failed.
        // Wrap cleanup in a new transaction to ensure atomicity.
        try {
          await client.query("BEGIN");
          await client.query("DELETE FROM engagement_states WHERE engagement_id = $1", [engagementId]);
          await client.query("DELETE FROM loop_budgets WHERE engagement_id = $1", [engagementId]);
          await client.query("DELETE FROM engagements WHERE id = $1", [engagementId]);
          await client.query("COMMIT");
        } catch (cleanupErr) {
          console.error("Cleanup after job push failure also failed:", cleanupErr);
          await client.query("ROLLBACK").catch(() => {});
        }
        throw new Error(`Job dispatch failed: ${jobError instanceof Error ? jobError.message : "unknown error"}`);
      }

      if (!jobPushed) {
        // Clean up if job wasn't pushed
        await client.query("DELETE FROM engagement_states WHERE engagement_id = $1", [engagementId]);
        await client.query("DELETE FROM loop_budgets WHERE engagement_id = $1", [engagementId]);
        await client.query("DELETE FROM engagements WHERE id = $1", [engagementId]);
        throw new Error("Failed to queue scan job");
      }

      const response = {
        engagement: engagementResult.rows[0],
        trace_id: traceId,
      };

      // Store result for idempotency (24h TTL)
      const cacheKey = idempotencyKey || generateAPIIdempotencyKey(
        session.user.id,
        "/api/engagement/create",
        body
      );
      await setAPIIdempotencyResult(
        cacheKey,
        JSON.stringify(response)
      );

      log.apiEnd('POST', '/api/engagement/create', 200, { engagementId, scanType: effectiveScanType });
      return NextResponse.json(response);
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  } catch (error: unknown) {
    log.error("Create engagement error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return createErrorResponse(
        "Unauthorized",
        ErrorCodes.UNAUTHORIZED,
        undefined,
        401,
      );
    }

    return createErrorResponse(
      "Failed to create engagement",
      ErrorCodes.INTERNAL_ERROR,
      undefined,
      500,
    );
  }
}
