// Reports list API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const client = await pool.connect();

    try {
      // Fetch compliance reports for this org
      const result = await client.query(
        `SELECT id, engagement_id, standard, title, status, created_at, updated_at
         FROM compliance_reports
         WHERE org_id = $1
         ORDER BY created_at DESC
         LIMIT 50`,
        [session.user.orgId],
      );

      const reports = result.rows.map((r: Record<string, unknown>) => ({
        id: r.id,
        name: r.title,
        type: "compliance" as const,
        engagement_id: r.engagement_id,
        status: r.status,
        format: "pdf" as const,
        created_at: r.created_at,
      }));

      return NextResponse.json({ reports });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Reports API error:", error);
    return NextResponse.json({ reports: [] });
  }
}
