import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

/**
 * GET /api/tools/performance
 *
 * Returns tool performance statistics over the last 7 days,
 * scoped to the authenticated user's organization.
 *
 * Query Parameters:
 * - days: Number of days to look back (default: 7)
 * - tool: Specific tool name to get stats for (optional)
 *
 * Requirements: 22.3, 22.4
 */
export async function GET(req: Request) {
  // Parse query parameters early so it's available in catch block
  const { searchParams } = new URL(req.url);
  const days = parseInt(searchParams.get("days") || "7", 10);

  try {
    // Verify authentication and get session with org context
    const session = await requireAuth();
    const orgId = session.user.orgId;

    const toolName = searchParams.get("tool");

    // Validate days parameter
    if (isNaN(days) || days < 1 || days > 365) {
      return NextResponse.json(
        { error: "Invalid 'days' parameter. Must be between 1 and 365." },
        { status: 400 },
      );
    }

    // If specific tool requested, get stats for that tool
    if (toolName) {
      const result = await pool.query(
        `
        SELECT 
          tm.tool_name,
          COUNT(*) as total_executions,
          SUM(CASE WHEN tm.success THEN 1 ELSE 0 END) as success_count,
          ROUND(AVG(tm.duration_ms)::numeric, 2) as avg_duration_ms,
          ROUND((SUM(CASE WHEN tm.success THEN 1 ELSE 0 END)::float / COUNT(*) * 100)::numeric, 2) as success_rate,
          MIN(tm.duration_ms) as min_duration_ms,
          MAX(tm.duration_ms) as max_duration_ms
        FROM tool_metrics tm
        JOIN engagements e ON tm.engagement_id = e.id
        WHERE tm.tool_name = $1
          AND e.org_id = $2
          AND tm.created_at >= NOW() - INTERVAL '1 day' * $3
        GROUP BY tm.tool_name
        `,
        [toolName, orgId, days],
      );

      if (result.rows.length === 0) {
        return NextResponse.json({
          tool: toolName,
          message: "No metrics found for this tool in the specified time range",
          stats: null,
        });
      }

      return NextResponse.json({
        tool: toolName,
        stats: result.rows[0],
        days,
      });
    }

    // Get performance stats for all tools scoped to user's org
    const result = await pool.query(
      `
      SELECT 
        tm.tool_name,
        COUNT(*) as total_executions,
        SUM(CASE WHEN tm.success THEN 1 ELSE 0 END) as success_count,
        ROUND(AVG(tm.duration_ms)::numeric, 2) as avg_duration_ms,
        ROUND((SUM(CASE WHEN tm.success THEN 1 ELSE 0 END)::float / COUNT(*) * 100)::numeric, 2) as success_rate,
        MIN(tm.duration_ms) as min_duration_ms,
        MAX(tm.duration_ms) as max_duration_ms
      FROM tool_metrics tm
      JOIN engagements e ON tm.engagement_id = e.id
      WHERE e.org_id = $1
        AND tm.created_at >= NOW() - INTERVAL '1 day' * $2
      GROUP BY tm.tool_name
      ORDER BY total_executions DESC
      `,
      [orgId, days],
    );

    // Calculate summary statistics
    const summary = {
      total_tools: result.rows.length,
      total_executions: result.rows.reduce(
        (sum, row) => sum + parseInt(row.total_executions),
        0,
      ),
      total_successes: result.rows.reduce(
        (sum, row) => sum + parseInt(row.success_count),
        0,
      ),
      overall_success_rate: 0,
      avg_duration_across_tools: 0,
    };

    // Calculate overall success rate
    if (summary.total_executions > 0) {
      summary.overall_success_rate = parseFloat(
        ((summary.total_successes / summary.total_executions) * 100).toFixed(2),
      );
    }

    // Calculate average duration across all tools
    if (result.rows.length > 0) {
      const totalAvgDuration = result.rows.reduce(
        (sum, row) => sum + parseFloat(row.avg_duration_ms || 0),
        0,
      );
      summary.avg_duration_across_tools = parseFloat(
        (totalAvgDuration / result.rows.length).toFixed(2),
      );
    }

    return NextResponse.json({
      tools: result.rows,
      summary,
      days,
      generated_at: new Date().toISOString(),
    });
  } catch (error: unknown) {
    console.error("Get tool performance error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    // Handle case where tool_metrics table is missing the engagement_id column
    // (schema migration not yet applied). Return empty stats gracefully instead of crashing.
    if (err.message?.includes("column") && err.message?.includes("does not exist")) {
      console.warn("Tool performance: missing column in tool_metrics table. Returning empty stats.");
      return NextResponse.json({
        tools: [],
        summary: {
          total_tools: 0,
          total_executions: 0,
          total_successes: 0,
          overall_success_rate: 0,
          avg_duration_across_tools: 0,
        },
        days,
        generated_at: new Date().toISOString(),
        warning: "tool_metrics table schema may need migration",
      });
    }

    return NextResponse.json(
      { error: "Failed to fetch tool performance statistics" },
      { status: 500 },
    );
  }
}
