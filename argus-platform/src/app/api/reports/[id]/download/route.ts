// GET /api/reports/[id]/download - Download a report
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const session = await requireAuth();
    const { id } = await params;
    
    const client = await pool.connect();
    try {
      // Find the report
      const result = await client.query(
        "SELECT id, engagement_id, standard, title, results, status, html_content FROM compliance_reports WHERE id = $1 AND org_id = $2",
        [id, session.user.orgId]
      );
      
      if (result.rows.length === 0) {
        return NextResponse.json({ error: "Report not found" }, { status: 404 });
      }
      
      const report = result.rows[0];
      
      if (report.status === "ready" && report.html_content) {
        return new NextResponse(report.html_content, {
          status: 200,
          headers: {
            "Content-Type": "text/html",
            "Content-Disposition": `attachment; filename="report-${report.id}.html"`,
          },
        });
      }

      if (report.status === "generating") {
        return NextResponse.json(
          { error: "Report is still generating" },
          { status: 202 }
        );
      }

      return NextResponse.json(
        { error: "Report not found" },
        { status: 404 }
      );
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Download report error:", error);
    return NextResponse.json({ error: "Failed to download report" }, { status: 500 });
  }
}