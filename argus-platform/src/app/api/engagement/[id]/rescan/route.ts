import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { v4 as uuidv4 } from "uuid";
import { pushJob } from "@/lib/redis";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

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
  const { id: engagementId } = await params;
  log.api('POST', '/api/engagement/[id]/rescan', { engagementId });
  try {
    const session = await requireAuth();
    await requireEngagementAccess(session, engagementId);
    const client = await pool.connect();

    let targetUrl: string = '';
    let authorizationProof = 'authorized_testing';
    let authorizedScope: any = null;
    let scanType = 'url';
    let scanAggressiveness = 'default';
    let rateLimitConfig = null;
    let foundOriginal = false;

    // Parse request body for fallback values (needed if original engagement is gone)
    let body: any = {};
    try { body = await _req.json(); } catch { /* no body, that's fine */ }

    // Try to look up the original engagement
    try {
      const sourceResult = await client.query(
        `SELECT target_url, authorization_proof, authorized_scope,
                scan_type, scan_aggressiveness, rate_limit_config
         FROM engagements WHERE id = $1`,
        [engagementId],
      );

      if (sourceResult.rows.length > 0) {
        const source = sourceResult.rows[0];
        targetUrl = source.target_url;
        authorizationProof = source.authorization_proof || 'authorized_testing';
        authorizedScope = source.authorized_scope;
        scanType = source.scan_type || 'url';
        scanAggressiveness = source.scan_aggressiveness || 'default';
        rateLimitConfig = source.rate_limit_config;
        foundOriginal = true;
      }
    } catch (lookupErr) {
      const msg = lookupErr instanceof Error ? lookupErr.message : String(lookupErr);
      if (!msg.includes('does not exist') && !msg.includes('NotFound')) {
        throw lookupErr; // Real DB error, not a "not found"
      }
    }

    // If original engagement was deleted, use request body as fallback
    if (!foundOriginal) {
      targetUrl = body.targetUrl || body.target_url || '';
      scanType = body.scanType || body.scan_type || 'url';
      scanAggressiveness = body.scanAggressiveness || body.scan_aggressiveness || 'default';
      authorizationProof = body.authorizationProof || body.authorization_proof || 'authorized_testing';
      if (body.authorizedScope || body.authorized_scope) {
        authorizedScope = body.authorizedScope || body.authorized_scope;
      }
      log.wsEvent('rescan-fallback', { engagementId, targetUrl, scanType });
      if (!targetUrl) {
        client.release();
        return NextResponse.json({
          error: 'Original engagement not found. Provide targetUrl in request body to scan a new target.',
          code: 'ENGAGEMENT_NOT_FOUND',
          engagementId,
        }, { status: 404 });
      }
    }

    try {
      await client.query("BEGIN");

    // Create new engagement with same target and settings
    const newEngagementId = uuidv4();
    await client.query(
      `INSERT INTO engagements
       (id, org_id, target_url, authorization_proof, authorized_scope, status, created_by, rate_limit_config, scan_type, scan_aggressiveness, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())`,
      [
        newEngagementId,
        session.user.orgId,
        targetUrl,
        authorizationProof,
        authorizedScope || JSON.stringify({ domains: [new URL(targetUrl).hostname] }),
        "created",
        session.user.id,
        rateLimitConfig,
        scanType,
        scanAggressiveness,
      ],
    );

    // Initialize loop budget with defaults
    await client.query(
      `INSERT INTO loop_budgets
       (id, engagement_id, max_cycles, max_depth, current_cycles, current_depth, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, NOW())`,
      [uuidv4(), newEngagementId, 5, 3, 0, 0],
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

    try {
      if (scanType === "repo") {
        await pushJob({
          type: "repo_scan",
          engagement_id: newEngagementId,
          target: targetUrl,
          repo_url: targetUrl,
          budget: { max_cycles: 5, max_depth: 3 },
          aggressiveness: scanAggressiveness,
          trace_id: traceId,
          created_at: new Date().toISOString(),
        });
      } else {
        await pushJob({
          type: "recon",
          engagement_id: newEngagementId,
          target: targetUrl,
          budget: { max_cycles: 5, max_depth: 3 },
          aggressiveness: scanAggressiveness,
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

    log.apiEnd('POST', `/api/engagement/${engagementId}/rescan`, 200, { newEngagementId, traceId });
    return NextResponse.json({
      engagement_id: newEngagementId,
      target_url: targetUrl,
      scan_type: scanType,
      trace_id: traceId,
    });
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
  } catch (error: unknown) {
    log.error("Rescan error:", error);
    const err = error as Error;

    const statusCode = err.message === "Unauthorized" ? 401 : err.message.startsWith("Forbidden") ? 403 : 500;
    log.apiEnd('POST', `/api/engagement/${engagementId || 'unknown'}/rescan`, statusCode);
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }

    return NextResponse.json(
      { error: "Failed to rescan engagement" },
      { status: 500 },
    );
  }
}
