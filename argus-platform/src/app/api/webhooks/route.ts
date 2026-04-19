// Webhook endpoint for external integrations
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function POST(req: NextRequest) {
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

      return NextResponse.json({
        success: true,
        webhook_id: result.rows[0].id,
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Webhook create error:", error);
    return NextResponse.json(
      { error: "Failed to create webhook" },
      { status: 500 },
    );
  }
}

export async function GET(req: NextRequest) {
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

      return NextResponse.json({ webhooks: result.rows });
    } finally {
      client.release();
    }
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to fetch webhooks" },
      { status: 500 },
    );
  }
}
