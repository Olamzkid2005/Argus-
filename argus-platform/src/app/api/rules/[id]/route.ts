/**
 * Individual Rule API
 * DELETE /api/rules/[id] - Delete a rule
 * PUT /api/rules/[id] - Update rule fields (status, name, description, etc.)
 */
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const session = await requireAuth();
    const orgId = (session.user as { orgId?: string }).orgId;

    if (!orgId) {
      return NextResponse.json(
        { error: "Session missing org ID" },
        { status: 401 }
      );
    }

    const { id } = params;
    const client = await pool.connect();
    try {
      // Verify ownership before deleting
      const check = await client.query(
        "SELECT id FROM custom_rules WHERE id = $1 AND org_id = $2",
        [id, orgId]
      );
      if (check.rowCount === 0) {
        return NextResponse.json(
          { error: "Rule not found" },
          { status: 404 }
        );
      }

      await client.query(
        "DELETE FROM custom_rules WHERE id = $1 AND org_id = $2",
        [id, orgId]
      );

      return NextResponse.json({ success: true });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    console.error("Delete rule error:", err.message);
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to delete rule", details: err.message },
      { status: 500 }
    );
  }
}

export async function PUT(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const session = await requireAuth();
    const orgId = (session.user as { orgId?: string }).orgId;

    if (!orgId) {
      return NextResponse.json(
        { error: "Session missing org ID" },
        { status: 401 }
      );
    }

    const { id } = params;
    const body = await req.json();
    const { name, description, severity, category, status, rule_yaml, tags } = body;

    const client = await pool.connect();
    try {
      // Verify ownership
      const check = await client.query(
        "SELECT id FROM custom_rules WHERE id = $1 AND org_id = $2",
        [id, orgId]
      );
      if (check.rowCount === 0) {
        return NextResponse.json(
          { error: "Rule not found" },
          { status: 404 }
        );
      }

      const updates: string[] = [];
      const values: unknown[] = [];
      let idx = 1;

      if (name !== undefined) {
        updates.push(`name = $${idx++}`);
        values.push(name);
      }
      if (description !== undefined) {
        updates.push(`description = $${idx++}`);
        values.push(description);
      }
      if (severity !== undefined) {
        updates.push(`severity = $${idx++}`);
        values.push(severity);
      }
      if (category !== undefined) {
        updates.push(`category = $${idx++}`);
        values.push(category);
      }
      if (status !== undefined) {
        updates.push(`status = $${idx++}`);
        values.push(status);
      }
      if (rule_yaml !== undefined) {
        updates.push(`rule_yaml = $${idx++}`);
        values.push(rule_yaml);
      }
      if (tags !== undefined) {
        updates.push(`tags = $${idx++}`);
        values.push(tags);
      }

      if (updates.length === 0) {
        return NextResponse.json(
          { error: "No fields to update" },
          { status: 400 }
        );
      }

      updates.push(`updated_at = CURRENT_TIMESTAMP`);
      values.push(id, orgId);

      const result = await client.query(
        `UPDATE custom_rules SET ${updates.join(", ")} WHERE id = $${idx++} AND org_id = $${idx++} RETURNING *`,
        values
      );

      return NextResponse.json({ rule: result.rows[0] });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    console.error("Update rule error:", err.message);
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to update rule", details: err.message },
      { status: 500 }
    );
  }
}
