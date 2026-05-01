// Webhook endpoint for external integrations
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function POST(req: NextRequest) {
  log.api('POST', '/api/webhooks');
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { webhook_url, events, engagement_id } = body;

    if (!webhook_url) {
      return NextResponse.json(
        { error: "webhook_url required" },
        { status: 400 },
      );
    }

    // Validate URL
    try {
      new URL(webhook_url);
    } catch {
      return NextResponse.json(
        { error: "Invalid webhook_url" },
        { status: 400 },
      );
    }

    const client = await pool.connect();

    try {
      // Create webhook subscription
      const result = await client.query(
        `
        INSERT INTO webhooks (org_id, webhook_url, events, engagement_id, created_by)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
      `,
        [
          session.user.orgId,
          webhook_url,
          JSON.stringify(events || []),
          engagement_id,
          session.user.id,
        ],
      );

      log.apiEnd('POST', '/api/webhooks', 200, { webhook_id: result.rows[0].id });
      return NextResponse.json({
        success: true,
        webhook_id: result.rows[0].id,
      });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Webhook create error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to create webhook" },
      { status: 500 },
    );
  }
}

export async function DELETE(req: NextRequest) {
  log.api('DELETE', '/api/webhooks');
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const id = searchParams.get("id");

    if (!id) {
      return NextResponse.json({ error: "webhook id required" }, { status: 400 });
    }

    const client = await pool.connect();
    try {
      const result = await client.query(
        `DELETE FROM webhooks WHERE id = $1 AND org_id = $2 RETURNING id`,
        [id, session.user.orgId],
      );
      if (result.rows.length === 0) {
        return NextResponse.json({ error: "Webhook not found" }, { status: 404 });
      }
      log.apiEnd('DELETE', '/api/webhooks', 200, { id });
      return NextResponse.json({ success: true });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to delete webhook" }, { status: 500 });
  }
}

export async function GET(req: NextRequest) {
  log.api('GET', '/api/webhooks');
  try {
    const session = await requireAuth();

    const client = await pool.connect();

    try {
      const result = await client.query(
        `
        SELECT id, webhook_url, events, engagement_id, created_at, last_triggered
        FROM webhooks
        WHERE org_id = $1
        ORDER BY created_at DESC
      `,
        [session.user.orgId],
      );

      log.apiEnd('GET', '/api/webhooks', 200, { count: result.rows.length });
      return NextResponse.json({ webhooks: result.rows });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch webhooks" },
      { status: 500 },
    );
  }
}
