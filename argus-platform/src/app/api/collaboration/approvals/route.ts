// Approval workflows API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const type = searchParams.get("type");

    // Fetch workflows
    const workflowsResult = await pool.query(
      `SELECT * FROM approval_workflows WHERE org_id = $1 AND is_active = true`,
      [session.user.orgId],
    );

    // Fetch pending approval requests
    let requestsQuery = `
      SELECT ar.*, aw.name as workflow_name, aw.workflow_type,
             e.target_url as engagement_target,
             requester.email as requester_email, requester.name as requester_name
      FROM approval_requests ar
      JOIN approval_workflows aw ON ar.workflow_id = aw.id
      LEFT JOIN engagements e ON ar.engagement_id = e.id
      JOIN users requester ON ar.requester_id = requester.id
      WHERE aw.org_id = $1
    `;
    const requestsParams: unknown[] = [session.user.orgId];

    if (type) {
      requestsQuery += ` AND aw.workflow_type = $${requestsParams.length + 1}`;
      requestsParams.push(type);
    }

    requestsQuery += ` ORDER BY ar.created_at DESC`;

    const requestsResult = await pool.query(requestsQuery, requestsParams);

    return NextResponse.json({
      workflows: workflowsResult.rows,
      requests: requestsResult.rows,
    });
  } catch (error) {
    console.error("Get approvals error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to fetch approvals" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { action, workflow_id, engagement_id, finding_id, notes } = body;

    if (action === "create_request") {
      if (!workflow_id) {
        return NextResponse.json({ error: "workflow_id is required" }, { status: 400 });
      }

      const result = await pool.query(
        `
        INSERT INTO approval_requests (workflow_id, engagement_id, finding_id, requester_id, notes)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        `,
        [workflow_id, engagement_id || null, finding_id || null, session.user.id, notes || null],
      );

      return NextResponse.json({ request: result.rows[0] });
    }

    if (action === "approve" || action === "reject") {
      const { request_id } = body;
      if (!request_id) {
        return NextResponse.json({ error: "request_id is required" }, { status: 400 });
      }

      const newStatus = action === "approve" ? "approved" : "rejected";
      const result = await pool.query(
        `
        UPDATE approval_requests
        SET status = $1, updated_at = NOW(),
            completed_steps = completed_steps || $2::jsonb
        WHERE id = $3
        RETURNING *
        `,
        [newStatus, JSON.stringify([{ step: 1, user_id: session.user.id, action, at: new Date().toISOString() }]), request_id],
      );

      if (result.rows.length === 0) {
        return NextResponse.json({ error: "Request not found" }, { status: 404 });
      }

      return NextResponse.json({ request: result.rows[0] });
    }

    return NextResponse.json({ error: "Invalid action" }, { status: 400 });
  } catch (error) {
    console.error("Approval action error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to process approval" }, { status: 500 });
  }
}
