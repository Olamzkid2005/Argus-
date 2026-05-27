// Engagement Templates API — list, create, update
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";
import { v4 as uuidv4 } from "uuid";

export async function GET(req: NextRequest) {
  log.api('GET', '/api/templates');
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const templateId = searchParams.get("id");

    const client = await pool.connect();
    try {
      if (templateId) {
        const result = await client.query(
          `SELECT id, org_id, created_by, name, description, config, created_at, updated_at
           FROM engagement_templates
           WHERE id = $1 AND org_id = $2`,
          [templateId, session.user.orgId],
        );
        if (result.rows.length === 0) {
          return NextResponse.json({ error: "Template not found" }, { status: 404 });
        }
        return NextResponse.json({ template: result.rows[0] });
      }

      const result = await client.query(
        `SELECT id, org_id, created_by, name, description, config, created_at, updated_at
         FROM engagement_templates
         WHERE org_id = $1
         ORDER BY created_at DESC`,
        [session.user.orgId],
      );
      return NextResponse.json({ templates: result.rows });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Templates API error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to fetch templates" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  log.api('POST', '/api/templates');
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { name, description, config } = body;

    if (!name || !name.trim()) {
      return NextResponse.json({ error: "Template name is required" }, { status: 400 });
    }

    if (!config || typeof config !== "object") {
      return NextResponse.json({ error: "Template config is required" }, { status: 400 });
    }

    const client = await pool.connect();
    try {
      const id = uuidv4();
      const result = await client.query(
        `INSERT INTO engagement_templates (id, org_id, created_by, name, description, config)
         VALUES ($1, $2, $3, $4, $5, $6)
         RETURNING id, name, description, config, created_at`,
        [id, session.user.orgId, session.user.id, name.trim(), description || "", JSON.stringify(config)],
      );

      log.apiEnd('POST', '/api/templates', 200, { templateId: id });
      return NextResponse.json({ template: result.rows[0] }, { status: 201 });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Create template error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to create template" }, { status: 500 });
  }
}

export async function PUT(req: NextRequest) {
  log.api('PUT', '/api/templates');
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { id, name, description, config } = body;

    if (!id) {
      return NextResponse.json({ error: "Template ID is required" }, { status: 400 });
    }

    const client = await pool.connect();
    try {
      // Build dynamic SET clause with only provided fields
      const updates: string[] = [];
      const params: unknown[] = [];
      let paramIdx = 1;

      if (name !== undefined) {
        if (!name.toString().trim()) {
          return NextResponse.json({ error: "Template name cannot be empty" }, { status: 400 });
        }
        updates.push(`name = $${paramIdx++}`);
        params.push(name.toString().trim());
      }
      if (description !== undefined) {
        updates.push(`description = $${paramIdx++}`);
        params.push(description);
      }
      if (config !== undefined) {
        if (typeof config !== "object") {
          return NextResponse.json({ error: "Template config must be a valid object" }, { status: 400 });
        }
        updates.push(`config = $${paramIdx++}`);
        params.push(JSON.stringify(config));
      }

      if (updates.length === 0) {
        return NextResponse.json({ error: "No fields to update" }, { status: 400 });
      }

      params.push(id, session.user.orgId);

      const result = await client.query(
        `UPDATE engagement_templates
         SET ${updates.join(", ")}
         WHERE id = $${paramIdx++} AND org_id = $${paramIdx}
         RETURNING id, name, description, config, created_at, updated_at`,
        params,
      );

      if (result.rows.length === 0) {
        return NextResponse.json({ error: "Template not found" }, { status: 404 });
      }

      log.apiEnd('PUT', `/api/templates/${id}`, 200);
      return NextResponse.json({ template: result.rows[0] });
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'code' in err && (err as { code: string }).code === '23505') {
        return NextResponse.json(
          { error: "A template with this name already exists in your organization" },
          { status: 409 },
        );
      }
      throw err;
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Update template error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to update template" }, { status: 500 });
  }
}
