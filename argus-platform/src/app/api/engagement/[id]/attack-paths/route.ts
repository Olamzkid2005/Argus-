// Attack Paths API — returns attack chains with chain exploit scripts
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

function tryParseJSON<T>(val: T): T | Record<string, unknown> {
  if (typeof val !== "string") return val as T;
  try { return JSON.parse(val); } catch { return val; }
}

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
        `SELECT ap.id, ap.engagement_id, ap.path_nodes, ap.risk_score,
                ap.normalized_severity, ap.chain_exploit_script, ap.created_at
         FROM attack_paths ap
         JOIN engagements e ON ap.engagement_id = e.id
         WHERE ap.engagement_id = $1 AND e.org_id = $2
         ORDER BY ap.risk_score DESC`,
        [id, session.user.orgId],
      );

      return NextResponse.json({
        attack_paths: result.rows.map((row) => ({
          ...row,
          chain_exploit_script: row.chain_exploit_script
            ? tryParseJSON(row.chain_exploit_script)
            : null,
        })),
      });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Attack paths API error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch attack paths" },
      { status: 500 },
    );
  }
}
