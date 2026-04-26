// DELETE /api/reports/[id] - Delete a report
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const session = await requireAuth();
    const { id } = await params;
    
    const client = await pool.connect();
    try {
      // Delete the report
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
    console.error("Delete report error:", error);
    return NextResponse.json({ error: "Failed to delete report" }, { status: 500 });
  }
}