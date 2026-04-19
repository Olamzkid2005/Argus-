// Organization security settings API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

/**
 * GET /api/org/security
 *
 * Returns security settings for the user's organization
 */
export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();

    const result = await pool.query(
      `SELECT id, name, plan, created_at,
              two_factor_required,
              ip_allowlist,
              session_timeout_minutes
       FROM organizations WHERE id = $1`,
      [session.user.orgId],
    );

    if (result.rows.length === 0) {
      return NextResponse.json(
        { error: "Organization not found" },
        { status: 404 },
      );
    }

    const org = result.rows[0];

    // Mask IP allowlist - only show first 2 IPs for security
    let maskedAllowlist: string[] = [];
    if (org.ip_allowlist && org.ip_allowlist.length > 0) {
      maskedAllowlist = org.ip_allowlist.slice(0, 2);
      if (org.ip_allowlist.length > 2) {
        maskedAllowlist.push(`... and ${org.ip_allowlist.length - 2} more`);
      }
    }

    return NextResponse.json({
      organization: {
        id: org.id,
        name: org.name,
        plan: org.plan,
        created_at: org.created_at,
        two_factor_required: org.two_factor_required,
        ip_allowlist_count: org.ip_allowlist?.length || 0,
        ip_allowlist_preview: maskedAllowlist,
        session_timeout_minutes: org.session_timeout_minutes || 30,
      },
    });
  } catch (error) {
    console.error("Get org security error:", error);
    return NextResponse.json(
      { error: "Failed to fetch organization security settings" },
      { status: 500 },
    );
  }
}

/**
 * PUT /api/org/security
 *
 * Update security settings for the organization
 */
export async function PUT(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();

    const { two_factor_required, ip_allowlist, session_timeout_minutes } = body;

    const updates: string[] = [];
    const values: unknown[] = [];
    let paramIndex = 1;

    if (two_factor_required !== undefined) {
      updates.push(`two_factor_required = $${paramIndex++}`);
      values.push(two_factor_required);
    }

    if (ip_allowlist !== undefined) {
      if (!Array.isArray(ip_allowlist)) {
        return NextResponse.json(
          { error: "ip_allowlist must be an array of IP addresses" },
          { status: 400 },
        );
      }
      updates.push(`ip_allowlist = $${paramIndex++}`);
      values.push(ip_allowlist);
    }

    if (session_timeout_minutes !== undefined) {
      if (session_timeout_minutes < 5 || session_timeout_minutes > 1440) {
        return NextResponse.json(
          { error: "session_timeout_minutes must be between 5 and 1440" },
          { status: 400 },
        );
      }
      updates.push(`session_timeout_minutes = $${paramIndex++}`);
      values.push(session_timeout_minutes);
    }

    if (updates.length === 0) {
      return NextResponse.json(
        { error: "No valid fields to update" },
        { status: 400 },
      );
    }

    values.push(session.user.orgId);

    const query = `
      UPDATE organizations 
      SET ${updates.join(", ")}, updated_at = NOW()
      WHERE id = $${paramIndex}
      RETURNING id, name
    `;

    const result = await pool.query(query, values);

    if (result.rows.length === 0) {
      return NextResponse.json(
        { error: "Organization not found" },
        { status: 404 },
      );
    }

    return NextResponse.json({
      success: true,
      message: "Security settings updated",
    });
  } catch (error) {
    console.error("Update org security error:", error);
    return NextResponse.json(
      { error: "Failed to update organization security settings" },
      { status: 500 },
    );
  }
}
