// POST /api/reports/generate - Generate a new report
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import crypto from "crypto";
import { pushJob } from "@/lib/redis";
import { log } from "@/lib/logger";

export async function POST(req: NextRequest) {
  log.api('POST', '/api/reports/generate');
  try {
    const session = await requireAuth();
    const body = await req.json();
    
    const { engagement_id, report_type = "full", report_id: providedReportId } = body;
    const reportId = providedReportId || crypto.randomUUID();
    
    if (!engagement_id) {
      return NextResponse.json(
        { error: "engagement_id is required" },
        { status: 400 }
      );
    }

    // Verify engagement exists and belongs to org
    const client = await pool.connect();
    try {
      const engResult = await client.query(
        "SELECT id, target_url, status FROM engagements WHERE id = $1 AND org_id = $2",
        [engagement_id, session.user.orgId]
      );
      
      if (engResult.rows.length === 0) {
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 }
        );
      }
      
      const engagement = engResult.rows[0];
      
      // Check if engagement is complete
      if (engagement.status !== "complete" && engagement.status !== "analyzing" && engagement.status !== "reporting") {
        return NextResponse.json(
          { error: "Engagement must be completed before generating report" },
          { status: 400 }
        );
      }
      
      // Insert placeholder row
      await client.query(
        `INSERT INTO compliance_reports (id, org_id, engagement_id, standard, title, status, html_content)
         VALUES ($1, $2, $3, $4, $5, $6, $7)`,
        [reportId, session.user.orgId, engagement_id, report_type, `${report_type} Report - ${engagement.target_url}`, "generating", ""]
      );

      // Trigger Celery task
      try {
        await pushJob({
          type: "full_report",
          engagement_id,
          target: engagement.target_url,
          report_id: reportId,
          budget: { max_cycles: 1, max_depth: 1 },
          trace_id: crypto.randomUUID(),
          created_at: new Date().toISOString(),
        });
      } catch (pushError) {
        console.error("Failed to push job to queue:", pushError);
        await client.query(
          "UPDATE compliance_reports SET status = $1 WHERE id = $2",
          ["failed", reportId]
        );
        return NextResponse.json(
          { error: "Failed to queue report generation" },
          { status: 500 }
        );
      }

      log.apiEnd('POST', '/api/reports/generate', 200, { reportId, engagement_id });
      return NextResponse.json({
        report_id: reportId,
        status: "generating",
        message: "Report generation started."
      });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Generate report error:", error);
    return NextResponse.json(
      { error: "Failed to generate report" },
      { status: 500 }
    );
  }
}