// Findings API route with pagination, filtering, sorting, and bulk operations
import { NextRequest, NextResponse } from "next/server";
import { createErrorResponse, ErrorCodes } from "@/lib/api/errors";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(req: NextRequest) {
  log.api('GET', '/api/findings', { query: req.nextUrl.search });
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);

    // Filter params
    const severity = searchParams.get("severity");
    const tool = searchParams.get("tool");
    const verified = searchParams.get("verified");
    const search = searchParams.get("search");
    const engagementId = searchParams.get("engagement_id");
    const groupBy = searchParams.get("group_by"); // "type" | "severity" | "source_tool" | null

    // Cap limit to prevent OOM (max 200)
    const limit = Math.min(Math.max(parseInt(searchParams.get("limit") || "50", 10) || 50, 1), 200);
    const page = Math.max(parseInt(searchParams.get("page") || "1", 10) || 1, 1);
    const offset = (page - 1) * limit;

    // Date range params
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");

    // Sorting params
    const sortBy = searchParams.get("sort_by") || "severity";
    const sortOrder = searchParams.get("sort_order") || "asc";

    const client = await pool.connect();

    try {
      // Build query with filters
      let query = `
        SELECT f.id, f.engagement_id, e.target_url, f.type, f.severity, f.endpoint, f.source_tool, 
               f.verified, f.confidence, f.created_at, f.evidence
        FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE e.org_id = $1
      `;
      const orgId = session.user.orgId || '';
      if (!orgId) {
        log.apiEnd('GET', '/api/findings', 400, { error: 'No org ID in session' });
        return createErrorResponse('No organization ID in session', ErrorCodes.VALIDATION_ERROR, undefined, 400);
      }
      const params: unknown[] = [orgId];
      let paramIndex = 2;

      if (severity && severity !== "ALL") {
        query += ` AND f.severity = $${paramIndex}`;
        params.push(severity);
        paramIndex++;
      }

      if (tool && tool !== "ALL") {
        query += ` AND f.source_tool = $${paramIndex}`;
        params.push(tool);
        paramIndex++;
      }

      if (verified === "true") {
        query += ` AND f.verified = true`;
      } else if (verified === "false") {
        query += ` AND f.verified = false`;
      }

      if (search) {
        query += ` AND (f.endpoint ILIKE $${paramIndex} OR f.type ILIKE $${paramIndex})`;
        params.push(`%${search}%`);
        paramIndex++;
      }

      if (engagementId && engagementId !== "all") {
        query += ` AND f.engagement_id = $${paramIndex}`;
        params.push(engagementId);
        paramIndex++;
      }

      // Date range filtering
      if (dateFrom) {
        query += ` AND f.created_at >= $${paramIndex}`;
        params.push(dateFrom);
        paramIndex++;
      }

      if (dateTo) {
        query += ` AND f.created_at <= $${paramIndex}`;
        params.push(dateTo);
        paramIndex++;
      }

      // Get total count
      const countQuery = query.replace(
        "SELECT f.id, f.engagement_id, e.target_url, f.type, f.severity, f.endpoint, f.source_tool, f.verified, f.confidence, f.created_at, f.evidence",
        "SELECT COUNT(*)",
      );
      const countResult = await client.query(countQuery, params);
      const total = countResult.rows[0] ? parseInt(countResult.rows[0].count) : 0;

      // Build dynamic ORDER BY clause based on sort parameters
      let orderClause = "";
      const validSortFields = [
        "severity",
        "created_at",
        "confidence",
        "endpoint",
        "type",
      ];
      const validSortOrders = ["asc", "desc"];

      const field = validSortFields.includes(sortBy) ? sortBy : "severity";
      const order = validSortOrders.includes(sortOrder) ? sortOrder : "desc";

      if (field === "severity") {
        // Severity needs custom ordering
        orderClause = ` ORDER BY 
          CASE f.severity 
            WHEN 'CRITICAL' THEN 1 
            WHEN 'HIGH' THEN 2 
            WHEN 'MEDIUM' THEN 3 
            WHEN 'LOW' THEN 4 
            ELSE 5 
          END ${order.toUpperCase()},
          f.created_at DESC`;
      } else if (field === "created_at") {
        orderClause = ` ORDER BY f.created_at ${order.toUpperCase()}`;
      } else if (field === "confidence") {
        orderClause = ` ORDER BY f.confidence ${order.toUpperCase()}`;
      } else if (field === "endpoint") {
        orderClause = ` ORDER BY f.endpoint ${order.toUpperCase()}`;
      } else if (field === "type") {
        orderClause = ` ORDER BY f.type ${order.toUpperCase()}`;
      }

      // Add ordering and pagination
      query += orderClause + ` LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
      params.push(limit, offset);

      const result = await client.query(query, params);

      // ── Group by mode ──
      let groups: Record<string, { findings: typeof result.rows; count: number; severities: Record<string, number> }> | undefined;
      if (groupBy && ["type", "severity", "source_tool"].includes(groupBy)) {
        groups = {};
        for (const row of result.rows) {
          const key = String(row[groupBy as keyof typeof row] || "OTHER");
          if (!groups[key]) {
            groups[key] = { findings: [], count: 0, severities: {} };
          }
          groups[key].findings.push(row);
          groups[key].count++;
          const sev = String(row.severity || "INFO");
          groups[key].severities[sev] = (groups[key].severities[sev] || 0) + 1;
        }
      }

      log.apiEnd('GET', '/api/findings', 200, { total, returned: result.rows.length, grouped: !!groupBy });
      const response = NextResponse.json({
        findings: result.rows,
        groups: groups ? Object.entries(groups).map(([key, val]) => ({
          key,
          count: val.count,
          severities: val.severities,
          findings: val.findings,
        })) : undefined,
        meta: {
          total,
          page,
          limit,
          totalPages: Math.ceil(total / limit),
          sort_by: sortBy,
          sort_order: sortOrder,
          group_by: groupBy || undefined,
        },
      });

      // Findings change frequently during active scanning — prevent caching of stale data
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
    const err = error as Error;
    log.error("Findings API error:", err.message || String(err));
    if (err.message === "Unauthorized") {
      return createErrorResponse(
        "Unauthorized",
        ErrorCodes.UNAUTHORIZED,
        undefined,
        401,
      );
    }
    return createErrorResponse(
      "Failed to fetch findings",
      ErrorCodes.INTERNAL_ERROR,
      undefined,
      500,
    );
  }
}

/**
 * POST /api/findings
 *
 * Bulk operations on findings:
 * - verify: Mark findings as verified
 * - delete: Delete findings
 * - update_severity: Change severity level
 */
export async function POST(req: NextRequest) {
  log.api('POST', '/api/findings');
  try {
    const session = await requireAuth();
    const body = await req.json();

    const { action, finding_ids, severity } = body;

    if (
      !action ||
      !finding_ids ||
      !Array.isArray(finding_ids) ||
      finding_ids.length === 0
    ) {
      return createErrorResponse(
        "Invalid request: action and finding_ids are required",
        ErrorCodes.BAD_REQUEST,
        undefined,
        400,
      );
    }

    // Verify user has access to all findings
    const client = await pool.connect();

    try {
      // Verify all findings belong to user's org
      const verifyQuery = `
        SELECT f.id FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE f.id = ANY($1) AND e.org_id = $2
      `;
      const verifyResult = await client.query(verifyQuery, [
        finding_ids,
        session.user.orgId,
      ]);

      if (verifyResult.rows.length !== finding_ids.length) {
        return createErrorResponse(
          "Some findings not found or access denied",
          ErrorCodes.FORBIDDEN,
          undefined,
          403,
        );
      }

      // Execute bulk action
      let result;
      switch (action) {
        case "verify":
          result = await client.query(
            `UPDATE findings SET verified = true, updated_at = NOW() WHERE id = ANY($1) RETURNING id`,
            [finding_ids],
          );
          break;

        case "delete":
          result = await client.query(
            `DELETE FROM findings WHERE id = ANY($1) RETURNING id`,
            [finding_ids],
          );
          break;

        case "update_severity":
          if (!severity) {
            return createErrorResponse(
              "severity is required for update_severity action",
              ErrorCodes.VALIDATION_ERROR,
              undefined,
              400,
            );
          }
          const validSeverities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
          if (!validSeverities.includes(severity)) {
            return createErrorResponse(
              `Invalid severity. Must be one of: ${validSeverities.join(", ")}`,
              ErrorCodes.VALIDATION_ERROR,
              undefined,
              400,
            );
          }
          result = await client.query(
            `UPDATE findings SET severity = $2, updated_at = NOW() WHERE id = ANY($1) RETURNING id`,
            [finding_ids, severity],
          );
          break;

        default:
          return createErrorResponse(
            `Invalid action: ${action}`,
            ErrorCodes.BAD_REQUEST,
            undefined,
            400,
          );
      }

      log.apiEnd('POST', '/api/findings', 200, { action, affected: result?.rowCount || 0 });
      return NextResponse.json({
        success: true,
        action,
        affected: result?.rowCount || 0,
      });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    log.error("Findings bulk operation error:", err.message || String(err));
    if (err.message === "Unauthorized") {
      return createErrorResponse(
        "Unauthorized",
        ErrorCodes.UNAUTHORIZED,
        undefined,
        401,
      );
    }
    return createErrorResponse(
      "Failed to perform bulk operation",
      ErrorCodes.INTERNAL_ERROR,
      undefined,
      500,
    );
  }
}
