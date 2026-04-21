// Finding assignments and workflow management API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const assignedTo = searchParams.get("assigned_to");
    const status = searchParams.get("status");

    let query = `
      SELECT fa.id, fa.status, fa.priority, fa.due_date, fa.created_at, fa.updated_at,
             f.id as finding_id, f.type as finding_type, f.severity, f.endpoint,
             u.id as assigned_to_id, u.email as assigned_to_email, u.name as assigned_to_name,
             assigner.email as assigned_by_email
      FROM finding_assignments fa
      JOIN findings f ON fa.finding_id = f.id
      JOIN engagements e ON f.engagement_id = e.id
      JOIN users u ON fa.assigned_to = u.id
      JOIN users assigner ON fa.assigned_by = assigner.id
      WHERE e.org_id = $1
    `;
    const params: unknown[] = [session.user.orgId];

    if (assignedTo) {
      query += ` AND fa.assigned_to = $${params.length + 1}`;
      params.push(assignedTo);
    }
    if (status) {
      query += ` AND fa.status = $${params.length + 1}`;
      params.push(status);
    }

    query += ` ORDER BY fa.created_at DESC`;

    const result = await pool.query(query, params);
    return NextResponse.json({ assignments: result.rows });
  } catch (error) {
    console.error("Get assignments error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to fetch assignments" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { finding_id, assigned_to, priority, due_date } = body;

    if (!finding_id || !assigned_to) {
      return NextResponse.json({ error: "finding_id and assigned_to are required" }, { status: 400 });
    }

    // Verify finding access
    const accessCheck = await pool.query(
      `SELECT 1 FROM findings f JOIN engagements e ON f.engagement_id = e.id WHERE f.id = $1 AND e.org_id = $2`,
      [finding_id, session.user.orgId],
    );
    if (accessCheck.rows.length === 0) {
      return NextResponse.json({ error: "Finding not found or access denied" }, { status: 403 });
    }

    const result = await pool.query(
      `
      INSERT INTO finding_assignments (finding_id, assigned_to, assigned_by, priority, due_date)
      VALUES ($1, $2, $3, $4, $5)
      ON CONFLICT (finding_id) DO UPDATE SET
        assigned_to = $2,
        assigned_by = $3,
        priority = $4,
        due_date = $5,
        status = 'open',
        updated_at = NOW()
      RETURNING *
      `,
      [finding_id, assigned_to, session.user.id, priority || "medium", due_date || null],
    );

    // Create notification for assigned user
    await pool.query(
      `INSERT INTO notifications (user_id, type, title, message, entity_type, entity_id)
       VALUES ($1, 'assignment', 'New Finding Assigned', $2, 'finding', $3)`,
      [
        assigned_to,
        `You have been assigned a finding: ${finding_id}`,
        finding_id,
      ],
    );

    return NextResponse.json({ assignment: result.rows[0] });
  } catch (error) {
    console.error("Create assignment error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to create assignment" }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { id, status } = body;

    if (!id || !status) {
      return NextResponse.json({ error: "id and status are required" }, { status: 400 });
    }

    const result = await pool.query(
      `
      UPDATE finding_assignments
      SET status = $1, updated_at = NOW()
      WHERE id = $2
      RETURNING *
      `,
      [status, id],
    );

    if (result.rows.length === 0) {
      return NextResponse.json({ error: "Assignment not found" }, { status: 404 });
    }

    return NextResponse.json({ assignment: result.rows[0] });
  } catch (error) {
    console.error("Update assignment error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to update assignment" }, { status: 500 });
  }
}
