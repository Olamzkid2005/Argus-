// Custom Rules API route
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);

    const status = searchParams.get("status") || "active";
    const category = searchParams.get("category");
    const limit = parseInt(searchParams.get("limit") || "50");
    const offset = parseInt(searchParams.get("offset") || "0");

    const orgId = (session.user as { orgId?: string }).orgId;
    if (!orgId) {
      console.error("GET /api/rules: missing orgId in session", session.user);
      return NextResponse.json(
        { error: "Session missing org ID. Try signing out and back in." },
        { status: 401 }
      );
    }

    const client = await pool.connect();

    try {
      let query = `
        SELECT id, name, description, severity, category, tags, status, version, is_community_shared, created_at, updated_at, rule_yaml
        FROM custom_rules
        WHERE org_id = $1
      `;
      const params: unknown[] = [orgId];
      let paramIndex = 2;

      if (status && status !== "all") {
        query += ` AND status = $${paramIndex}`;
        params.push(status);
        paramIndex++;
      }

      if (category && category !== "all") {
        query += ` AND category = $${paramIndex}`;
        params.push(category);
        paramIndex++;
      }

      query += ` ORDER BY updated_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
      params.push(limit, offset);

      const result = await client.query(query, params);

      return NextResponse.json({ rules: result.rows });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    console.error("Rules API GET error:", err.message, err.stack);
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch rules" },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();

    const { name, description, rule_yaml, severity, category, tags } = body;

    if (!name || !rule_yaml) {
      return NextResponse.json(
        { error: "name and rule_yaml are required" },
        { status: 400 },
      );
    }

    const orgId = (session.user as { orgId?: string }).orgId;
    const userId = (session.user as { id?: string }).id;

    if (!orgId || !userId) {
      console.error("Create rule: missing orgId or userId in session", {
        orgId,
        userId,
        sessionUser: session.user,
      });
      return NextResponse.json(
        { error: "Session missing org or user ID. Try signing out and back in." },
        { status: 401 }
      );
    }

    const client = await pool.connect();

    try {
      const result = await client.query(
        `
        INSERT INTO custom_rules (org_id, created_by, name, description, rule_yaml, severity, category, tags, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active')
        RETURNING id, name, status, version, created_at
        `,
        [
          orgId,
          userId,
          name,
          description || "",
          rule_yaml,
          severity || "MEDIUM",
          category || "custom",
          tags || [],
        ],
      );

      return NextResponse.json({ rule: result.rows[0] }, { status: 201 });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    console.error("Create rule error:", err.message, err.stack);
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to create rule" },
      { status: 500 }
    );
  }
}
