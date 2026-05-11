// Team collaboration and role-based permissions API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(req: NextRequest) {
  log.api('GET', '/api/collaboration/team');
  try {
    const session = await requireAuth();
    const result = await pool.query(
      `
      SELECT tm.id, tm.team_role, tm.invitation_status, tm.created_at,
             u.id as user_id, u.email, u.name, u.role as global_role
      FROM team_members tm
      JOIN users u ON tm.user_id = u.id
      WHERE tm.org_id = $1
      ORDER BY tm.created_at DESC
      LIMIT 200
      `,
      [session.user.orgId],
    );

    log.apiEnd('GET', '/api/collaboration/team', 200, { count: result.rows.length });
    return NextResponse.json({ members: result.rows });
  } catch (error) {
    log.error("Get team error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to fetch team members" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  log.api('POST', '/api/collaboration/team');
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { email, team_role } = body;
    log.api('POST', '/api/collaboration/team', { email, team_role });

    if (!email) {
      return NextResponse.json({ error: "Email is required" }, { status: 400 });
    }

    // Find user by email
    const userResult = await pool.query("SELECT id FROM users WHERE email = $1", [email]);
    if (userResult.rows.length === 0) {
      return NextResponse.json({ error: "User not found" }, { status: 404 });
    }

    const userId = userResult.rows[0].id;

    await pool.query(
      `
      INSERT INTO team_members (org_id, user_id, team_role, invited_by, invitation_status)
      VALUES ($1, $2, $3, $4, 'active')
      ON CONFLICT (org_id, user_id) DO UPDATE SET team_role = $3, updated_at = NOW()
      `,
      [session.user.orgId, userId, team_role || "member", session.user.id],
    );

    log.apiEnd('POST', '/api/collaboration/team', 200, { email });
    return NextResponse.json({ success: true });
  } catch (error) {
    log.error("Add team member error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to add team member" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  log.api('DELETE', '/api/collaboration/team');
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const id = searchParams.get("id");

    if (!id) {
      return NextResponse.json({ error: "Member ID is required" }, { status: 400 });
    }

    await pool.query(
      `DELETE FROM team_members WHERE id = $1 AND org_id = $2`,
      [id, session.user.orgId],
    );

    log.apiEnd('DELETE', '/api/collaboration/team', 200, { memberId: id });
    return NextResponse.json({ success: true });
  } catch (error) {
    log.error("Remove team member error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to remove team member" }, { status: 500 });
  }
}
