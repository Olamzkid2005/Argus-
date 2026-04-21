import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id } = await params;

    const client = await pool.connect();

    try {
      const result = await client.query(
        `
        SELECT cr.id, cr.engagement_id, cr.standard, cr.title, cr.report_data,
               cr.html_content, cr.status, cr.created_at, cr.updated_at
        FROM compliance_reports cr
        JOIN engagements e ON cr.engagement_id = e.id
        WHERE cr.id = $1 AND e.org_id = $2
        `,
        [id, session.user.orgId],
      );

      if (result.rows.length === 0) {
        return NextResponse.json(
          { error: "Report not found" },
          { status: 404 },
        );
      }

      return NextResponse.json({ report: result.rows[0] });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Get compliance report error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch compliance report" },
      { status: 500 },
    );
  }
}
