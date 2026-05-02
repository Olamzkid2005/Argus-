// Scheduled engagements management API
// Used by the Settings page UI for creating, listing, and deleting scheduled scans
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET() {
  log.api("GET", "/api/reports/scheduled");
  try {
    const session = await requireAuth();
    const result = await pool.query(
      `
      SELECT id, target_url, scan_type, aggressiveness, agent_mode,
             cron_expression, next_run_at, last_run_at, enabled, created_at
      FROM scheduled_engagements
      WHERE org_id = $1
      ORDER BY created_at DESC
      `,
      [session.user.orgId],
    );

    log.apiEnd("GET", "/api/reports/scheduled", 200, { count: result.rows.length });
    return NextResponse.json({ schedules: result.rows });
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    log.error("Get scheduled scans error:", err.message || String(err));
    return NextResponse.json({ error: "Failed to fetch scheduled scans" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  log.api("POST", "/api/reports/scheduled");
  try {
    const session = await requireAuth();
    const body = await req.json();

    // Route to correct table based on payload shape
    const hasTargetUrl = !!body.target_url;

    if (hasTargetUrl) {
      // ── Scheduled Scan (scheduled_engagements table) ──
      const { target_url, scan_type, aggressiveness, agent_mode, cron_expression } = body;

      if (!target_url || !cron_expression) {
        return NextResponse.json({ error: "target_url and cron_expression are required" }, { status: 400 });
      }

      // Calculate next_run_at from cron
      const now = new Date();
      let nextRun = new Date(now);
      if (cron_expression === "0 2 * * *") {
        nextRun.setDate(nextRun.getDate() + 1);
        nextRun.setHours(2, 0, 0, 0);
      } else if (cron_expression === "0 2 * * 1") {
        nextRun.setDate(nextRun.getDate() + (8 - nextRun.getDay()) % 7 || 7);
        nextRun.setHours(2, 0, 0, 0);
      } else if (cron_expression === "0 2 1 * *") {
        nextRun.setMonth(nextRun.getMonth() + 1);
        nextRun.setDate(1);
        nextRun.setHours(2, 0, 0, 0);
      } else {
        nextRun.setDate(nextRun.getDate() + 7);
      }

      const result = await pool.query(
        `
        INSERT INTO scheduled_engagements
          (org_id, created_by, target_url, authorized_scope, scan_type,
           aggressiveness, agent_mode, cron_expression, next_run_at)
        VALUES ($1, $2, $3, '{}', $4, $5, $6, $7, $8)
        RETURNING id, target_url, scan_type, aggressiveness, agent_mode,
                  cron_expression, next_run_at, created_at
        `,
        [session.user.orgId, session.user.id, target_url, scan_type || "url",
         aggressiveness || "default", agent_mode !== false, cron_expression, nextRun.toISOString()],
      );

      log.apiEnd("POST", "/api/reports/scheduled", 200, { id: result.rows[0].id, type: "scan" });
      return NextResponse.json({ schedule: result.rows[0] });
    } else {
      // ── Scheduled Report (scheduled_reports table, legacy) ──
      const { name, report_type, frequency, email_recipients, engagement_ids } = body;

      if (!name || !frequency || !email_recipients || !Array.isArray(email_recipients) || email_recipients.length === 0) {
        return NextResponse.json({ error: "Name, frequency, and email_recipients are required" }, { status: 400 });
      }

      const now = new Date();
      let nextRun = new Date(now);
      switch (frequency) {
        case "daily":    nextRun.setDate(nextRun.getDate() + 1); break;
        case "weekly":   nextRun.setDate(nextRun.getDate() + 7); break;
        case "monthly":  nextRun.setMonth(nextRun.getMonth() + 1); break;
        case "quarterly":nextRun.setMonth(nextRun.getMonth() + 3); break;
        default:         nextRun.setDate(nextRun.getDate() + 7);
      }

      const result = await pool.query(
        `
        INSERT INTO scheduled_reports (org_id, created_by, name, report_type, frequency, engagement_ids, email_recipients, next_run_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        `,
        [session.user.orgId, session.user.id, name, report_type || "summary", frequency, engagement_ids || null, email_recipients, nextRun.toISOString()],
      );

      log.apiEnd("POST", "/api/reports/scheduled", 200, { id: result.rows[0].id, type: "report" });
      return NextResponse.json({ report: result.rows[0] });
    }
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    log.error("Create scheduled scan/report error:", err.message || String(err));
    return NextResponse.json({ error: "Failed to create scheduled scan" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  log.api("DELETE", "/api/reports/scheduled");
  try {
    const session = await requireAuth();
    const body = await req.json().catch(() => ({}));
    // Support both query param and body for id
    const { searchParams } = new URL(req.url);
    const id = searchParams.get("id") || body.id;

    if (!id) {
      return NextResponse.json({ error: "Schedule ID is required" }, { status: 400 });
    }

    // Delete from scheduled_engagements with org isolation
    await pool.query(
      `DELETE FROM scheduled_engagements WHERE id = $1 AND org_id = $2`,
      [id, session.user.orgId],
    );

    log.apiEnd("DELETE", "/api/reports/scheduled", 200, { id });
    return NextResponse.json({ success: true });
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    log.error("Delete scheduled scan error:", err.message || String(err));
    return NextResponse.json({ error: "Failed to delete scheduled scan" }, { status: 500 });
  }
}
