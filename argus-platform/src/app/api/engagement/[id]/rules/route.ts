import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pool } from "@/lib/db";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: engagementId } = await params;
  try {
    const session = await requireAuth();
    await requireEngagementAccess(session, engagementId);

    const client = await pool.connect();
    try {
      const result = await client.query(
        `SELECT cr.id, cr.name, cr.description, cr.severity, cr.category,
                cr.tags, cr.status, cr.version, cr.created_at, cr.updated_at,
                ecr.created_at as linked_at
         FROM custom_rules cr
         INNER JOIN engagement_custom_rules ecr ON cr.id = ecr.rule_id
         WHERE ecr.engagement_id = $1
         ORDER BY ecr.created_at DESC`,
        [engagementId],
      );

      return NextResponse.json({ rules: result.rows });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch engagement rules" },
      { status: 500 },
    );
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: engagementId } = await params;
  try {
    const session = await requireAuth();
    await requireEngagementAccess(session, engagementId);

    const { ruleIds } = await req.json();

    if (!Array.isArray(ruleIds) || ruleIds.length === 0) {
      return NextResponse.json(
        { error: "ruleIds must be a non-empty array" },
        { status: 400 },
      );
    }

    const client = await pool.connect();
    try {
      await client.query("BEGIN");

      const orgId = (session.user as { orgId?: string }).orgId;
      for (const ruleId of ruleIds) {
        const ownership = await client.query(
          "SELECT id FROM custom_rules WHERE id = $1 AND org_id = $2",
          [ruleId, orgId],
        );
        if (ownership.rowCount === 0) {
          await client.query("ROLLBACK");
          return NextResponse.json(
            { error: `Rule ${ruleId} not found or not in your org` },
            { status: 404 },
          );
        }

        await client.query(
          `INSERT INTO engagement_custom_rules (engagement_id, rule_id)
           VALUES ($1, $2)
           ON CONFLICT DO NOTHING`,
          [engagementId, ruleId],
        );
      }

      await client.query("COMMIT");

      return NextResponse.json({ success: true }, { status: 201 });
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to link rules to engagement" },
      { status: 500 },
    );
  }
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: engagementId } = await params;
  try {
    const session = await requireAuth();
    await requireEngagementAccess(session, engagementId);

    const { ruleIds } = await req.json();

    if (!Array.isArray(ruleIds) || ruleIds.length === 0) {
      return NextResponse.json(
        { error: "ruleIds must be a non-empty array" },
        { status: 400 },
      );
    }

    const client = await pool.connect();
    try {
      await client.query(
        `DELETE FROM engagement_custom_rules
         WHERE engagement_id = $1 AND rule_id = ANY($2::uuid[])`,
        [engagementId, ruleIds],
      );

      return NextResponse.json({ success: true });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to unlink rules from engagement" },
      { status: 500 },
    );
  }
}
