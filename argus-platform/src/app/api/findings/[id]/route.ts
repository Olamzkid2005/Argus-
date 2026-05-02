// GET /api/findings/[id] — individual finding details with org-level access control
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  log.api("GET", `/api/findings/${id}`);
  try {
    const session = await requireAuth();

    const client = await pool.connect();
    try {
      const result = await client.query(
        `SELECT f.*, e.target_url, e.org_id
         FROM findings f
         JOIN engagements e ON f.engagement_id = e.id
         WHERE f.id = $1 AND e.org_id = $2`,
        [id, session.user.orgId],
      );

      if (!result.rows.length) {
        return NextResponse.json({ error: "Not found" }, { status: 404 });
      }

      const finding = result.rows[0];

      log.apiEnd("GET", `/api/findings/${id}`, 200, {
        type: finding.type,
        severity: finding.severity,
      });
      return NextResponse.json({ finding });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    log.error("Finding detail error:", err.message || String(err));
    return NextResponse.json(
      { error: "Failed to fetch finding" },
      { status: 500 },
    );
  }
}
