// Engagement Templates API — delete single template
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id } = await params;

    const client = await pool.connect();
    try {
      const result = await client.query(
        `DELETE FROM engagement_templates WHERE id = $1 AND org_id = $2 RETURNING id`,
        [id, session.user.orgId],
      );

      if (result.rows.length === 0) {
        return NextResponse.json({ error: "Template not found" }, { status: 404 });
      }

      log.apiEnd('DELETE', `/api/templates/${id}`, 200);
      return NextResponse.json({ deleted: true });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Delete template error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to delete template" }, { status: 500 });
  }
}
