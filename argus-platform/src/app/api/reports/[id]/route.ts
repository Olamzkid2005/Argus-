// GET /api/reports/[id] - Get a report by engagement ID
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  log.api("GET", "/api/reports/[id]");
  try {
    const session = await requireAuth();
    const { id } = await params;
    log.api("GET", "/api/reports/[id]", { engagementId: id });

    const client = await pool.connect();
    try {
      const result = await client.query(
        `SELECT id, engagement_id, generated_by, executive_summary,
                full_report_json, risk_level, total_findings,
                critical_count, high_count, medium_count, low_count,
                model_used, created_at
         FROM reports
         WHERE engagement_id = $1
         LIMIT 1`,
        [id]
      );

      if (result.rows.length === 0) {
        log.apiEnd("GET", `/api/reports/${id}`, 404);
        return NextResponse.json({ error: "Report not found" }, { status: 404 });
      }

      const report = result.rows[0];
      if (typeof report.full_report_json === "string") {
        try {
          report.full_report_json = JSON.parse(report.full_report_json);
        } catch {}
      }

      log.apiEnd("GET", `/api/reports/${id}`, 200);
      return NextResponse.json({ report });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Get report error:", error);
    return NextResponse.json({ error: "Failed to fetch report" }, { status: 500 });
  }
}

// DELETE /api/reports/[id] - Delete a report
export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  log.api("DELETE", "/api/reports/[id]");
  try {
    const session = await requireAuth();
    const { id } = await params;
    const client = await pool.connect();
    try {
      const result = await client.query(
        "DELETE FROM compliance_reports WHERE id = $1 AND org_id = $2 RETURNING id",
        [id, session.user.orgId]
      );
      if (result.rows.length === 0) {
        return NextResponse.json({ error: "Report not found" }, { status: 404 });
      }
      return NextResponse.json({ success: true, report_id: id });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Delete report error:", error);
    return NextResponse.json({ error: "Failed to delete report" }, { status: 500 });
  }
}
