// Execution logs endpoint
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

/**
 * GET /api/logs
 *
 * Returns execution logs with filtering and pagination
 */
export async function GET(req: Request) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);

    // Get query parameters
    const page = parseInt(searchParams.get("page") || "1");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);
    const offset = (page - 1) * limit;

    const level = searchParams.get("level");
    const eventType = searchParams.get("event_type");
    const traceId = searchParams.get("trace_id");
    const engagementId = searchParams.get("engagement_id");

    const client = await pool.connect();

    try {
      const orgId = (session.user as { orgId?: string }).orgId;

      // Build query
      let query = `
        SELECT 
          el.id,
          el.trace_id,
          el.engagement_id,
          el.log_level,
          el.event_type,
          el.message,
          el.metadata,
          el.created_at
        FROM execution_logs el
        JOIN engagements e ON e.id = el.engagement_id
        WHERE e.org_id = $1
          AND el.trace_id IS NOT NULL
      `;
      const params: unknown[] = [orgId];
      let paramIndex = 2;

      if (level) {
        query += ` AND el.log_level = $${paramIndex}`;
        params.push(level.toUpperCase());
        paramIndex++;
      }

      if (eventType) {
        query += ` AND el.event_type = $${paramIndex}`;
        params.push(eventType);
        paramIndex++;
      }

      if (traceId) {
        query += ` AND el.trace_id = $${paramIndex}`;
        params.push(traceId);
        paramIndex++;
      }

      if (engagementId) {
        query += ` AND el.engagement_id = $${paramIndex}`;
        params.push(engagementId);
        paramIndex++;
      }

      // Get total count
      const countQuery = query.replace(
        /SELECT [\s\S]*?FROM/,
        "SELECT COUNT(*) FROM",
      );
      const countResult = await client.query(countQuery, params);
      const total = parseInt(countResult.rows[0].count);

      // Add ordering and pagination
      query += ` ORDER BY el.created_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
      params.push(limit, offset);

      const result = await client.query(query, params);

      return NextResponse.json({
        logs: result.rows,
        meta: {
          total,
          page,
          limit,
          totalPages: Math.ceil(total / limit),
        },
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Logs error:", error);
    return NextResponse.json(
      { error: "Failed to fetch logs" },
      { status: 500 }
    );
  }
}