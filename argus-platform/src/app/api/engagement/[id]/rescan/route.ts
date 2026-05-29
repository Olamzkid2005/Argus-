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

    let agentMode = false;
    let scanMode = 'agent';
    let bugBountyMode = false;
    let authConfig = null;
    let dualAuthConfig = null;

    // Try to look up the original engagement
    try {
      const sourceResult = await client.query(
        `SELECT target_url, authorization_proof, authorized_scope,
                scan_type, scan_aggressiveness, rate_limit_config,
                agent_mode, scan_mode, bug_bounty_mode,
                auth_config, dual_auth_config
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
        agentMode = source.agent_mode || false;
        scanMode = source.scan_mode || 'agent';
        bugBountyMode = source.bug_bounty_mode || false;
        authConfig = source.auth_config;
        dualAuthConfig = source.dual_auth_config;
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
       (id, org_id, target_url, authorization_proof, authorized_scope, status, created_by, rate_limit_config, auth_config, dual_auth_config, scan_type, scan_aggressiveness, agent_mode, scan_mode, bug_bounty_mode, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, NOW())`,
      [
        newEngagementId,
        session.user.orgId,
        targetUrl,
        authorizationProof,
        authorizedScope || (() => { try { return JSON.stringify({ domains: [new URL(targetUrl).hostname] }); } catch { return JSON.stringify({ domains: [] }); } })(),
        "created",
        session.user.id,
        rateLimitConfig,
        authConfig,
        dualAuthConfig,
        scanType,
        scanAggressiveness,
        agentMode,
        scanMode,
        bugBountyMode,
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
          agent_mode: agentMode,
          scan_mode: scanMode,
          bug_bounty_mode: bugBountyMode,
          auth_config: authConfig,
          dual_auth_config: dualAuthConfig,
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
          agent_mode: agentMode,
          scan_mode: scanMode,
          bug_bounty_mode: bugBountyMode,
          auth_config: authConfig,
          dual_auth_config: dualAuthConfig,
          trace_id: traceId,
          created_at: new Date().toISOString(),
        });
      }
    } catch (jobError) {
      // Rollback if job push fails — clean up all related records
      await client.query("BEGIN");
      await client.query("DELETE FROM engagement_states WHERE engagement_id = $1", [newEngagementId]);
      await client.query("DELETE FROM loop_budgets WHERE engagement_id = $1", [newEngagementId]);
      await client.query("DELETE FROM engagements WHERE id = $1", [newEngagementId]);
      await client.query("COMMIT");
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
