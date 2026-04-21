// Scheduled reports management API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const result = await pool.query(
      `
      SELECT id, name, report_type, frequency, is_active, next_run_at, email_recipients, created_at
      FROM scheduled_reports
      WHERE org_id = $1
      ORDER BY created_at DESC
      `,
      [session.user.orgId],
    );

    return NextResponse.json({ reports: result.rows });
  } catch (error) {
    console.error("Get scheduled reports error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to fetch scheduled reports" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { name, report_type, frequency, email_recipients, engagement_ids } = body;

    if (!name || !frequency || !email_recipients || !Array.isArray(email_recipients) || email_recipients.length === 0) {
      return NextResponse.json({ error: "Name, frequency, and email_recipients are required" }, { status: 400 });
    }

    // Calculate next run based on frequency
    const now = new Date();
    let nextRun = new Date(now);
    switch (frequency) {
      case "daily":
        nextRun.setDate(nextRun.getDate() + 1);
        break;
      case "weekly":
        nextRun.setDate(nextRun.getDate() + 7);
        break;
      case "monthly":
        nextRun.setMonth(nextRun.getMonth() + 1);
        break;
      case "quarterly":
        nextRun.setMonth(nextRun.getMonth() + 3);
        break;
      default:
        nextRun.setDate(nextRun.getDate() + 7);
    }

    const result = await pool.query(
      `
      INSERT INTO scheduled_reports (org_id, created_by, name, report_type, frequency, engagement_ids, email_recipients, next_run_at)
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
      RETURNING *
      `,
      [session.user.orgId, session.user.id, name, report_type || "summary", frequency, engagement_ids || null, email_recipients, nextRun.toISOString()],
    );

    return NextResponse.json({ report: result.rows[0] });
  } catch (error) {
    console.error("Create scheduled report error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to create scheduled report" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const id = searchParams.get("id");

    if (!id) {
      return NextResponse.json({ error: "Report ID is required" }, { status: 400 });
    }

    await pool.query(
      `DELETE FROM scheduled_reports WHERE id = $1 AND org_id = $2`,
      [id, session.user.orgId],
    );

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Delete scheduled report error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to delete scheduled report" }, { status: 500 });
  }
}
