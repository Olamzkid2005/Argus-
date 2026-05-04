// Engagements list API with pagination and sorting
import { NextRequest, NextResponse } from "next/server";
import { createErrorResponse, ErrorCodes } from "@/lib/api/errors";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);

    // Pagination
    const page = parseInt(searchParams.get("page") || "1");
    const limit = parseInt(searchParams.get("limit") || "10");
    const offset = (page - 1) * limit;

    // Filters
    const status = searchParams.get("status");
    const search = searchParams.get("search");

    // Date range params
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");

    // Sorting params
    const sortBy = searchParams.get("sort_by") || "created_at";
    const sortOrder = searchParams.get("sort_order") || "desc";

    const client = await pool.connect();

    try {
      // Build query - using joins instead of subqueries to avoid N+1
      let query = `
        SELECT 
          e.id, e.target_url, e.status, e.scan_type, e.created_at, 
          e.updated_at, e.completed_at,
          u.email as created_by_email,
          lb.max_cycles, lb.current_cycles,
          COALESCE(fc.findings_count, 0) as findings_count,
          COALESCE(fc.critical_count, 0) as critical_count
        FROM engagements e
        LEFT JOIN users u ON e.created_by = u.id
        LEFT JOIN loop_budgets lb ON e.id = lb.engagement_id
        LEFT JOIN (
          SELECT engagement_id, 
            COUNT(*) as findings_count,
            COUNT(CASE WHEN severity = 'CRITICAL' THEN 1 END) as critical_count
          FROM findings 
          GROUP BY engagement_id
        ) fc ON e.id = fc.engagement_id
        WHERE e.org_id = $1
      `;
      const params: unknown[] = [session.user.orgId];
      let paramIndex = 2;

      if (status && status !== "ALL") {
        query += ` AND e.status = $${paramIndex}`;
        params.push(status);
        paramIndex++;
      }

      if (search) {
        query += ` AND e.target_url ILIKE $${paramIndex}`;
        params.push(`%${search}%`);
        paramIndex++;
      }

      // Date range filtering
      if (dateFrom) {
        query += ` AND e.created_at >= $${paramIndex}`;
        params.push(dateFrom);
        paramIndex++;
      }

      if (dateTo) {
        query += ` AND e.created_at <= $${paramIndex}`;
        params.push(dateTo);
        paramIndex++;
      }

      // Get total count
      const countQuery = query.replace(
        /SELECT [\s\S]*?FROM/,
        "SELECT COUNT(*) FROM",
      );
      const countResult = await client.query(countQuery, params);
      const total = parseInt(countResult.rows[0].count);

      // Build dynamic ORDER BY clause
      const validSortFields = [
        "created_at",
        "updated_at",
        "target_url",
        "status",
      ];
      const validSortOrders = ["asc", "desc"];

      const field = validSortFields.includes(sortBy) ? sortBy : "created_at";
      const order = validSortOrders.includes(sortOrder) ? sortOrder : "desc";

      const orderClause = ` ORDER BY e.${field} ${order.toUpperCase()}`;

      // Add ordering and pagination
      query += orderClause + ` LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
      params.push(limit, offset);

      const result = await client.query(query, params);

      const response = NextResponse.json({
        engagements: result.rows,
        meta: {
          total,
          page,
          limit,
          totalPages: Math.ceil(total / limit),
          sort_by: sortBy,
          sort_order: sortOrder,
        },
      });

      // Prevent caching to ensure engagement list is always fresh after mutations
      response.headers.set(
        "Cache-Control",
        "private, no-cache, no-store, must-revalidate",
      );
      response.headers.set("X-Hits", result.rows.length.toString());

      return response;
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Engagements API error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return createErrorResponse(
        "Unauthorized",
        ErrorCodes.UNAUTHORIZED,
        undefined,
        401,
      );
    }
    return createErrorResponse(
      "Failed to fetch engagements",
      ErrorCodes.INTERNAL_ERROR,
      undefined,
      500,
    );
  }
}
