// Observability summary endpoint
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

/**
 * GET /api/observability
 *
 * Returns system observability data including:
 * - Active engagements
 * - Recent executions
 * - Error rates
 * - Performance metrics
 */
export async function GET(req: Request) {
  try {
    await requireAuth();
    const { searchParams } = new URL(req.url);
    const period = searchParams.get("period") || "24h";

    const client = await pool.connect();

    try {
      // Get engagement stats
      const engagementStats = await client.query(`
        SELECT 
          status,
          COUNT(*) as count
        FROM engagements
        WHERE created_at > NOW() - INTERVAL '1 hour' * $1
        GROUP BY status
      `, [period === "24h" ? 24 : period === "7d" ? 168 : 720]);

      // Get execution stats
      const executionStats = await client.query(`
        SELECT 
          COUNT(*) as total_executions,
          SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) as successful,
          SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
        FROM job_states
        WHERE created_at > NOW() - INTERVAL '1 hour' * $1
      `, [period === "24h" ? 24 : period === "7d" ? 168 : 720]);

      // Get average execution time
      const avgExecutionTime = await client.query(`
        SELECT 
          AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration
        FROM job_states
        WHERE completed_at IS NOT NULL
          AND created_at > NOW() - INTERVAL '1 hour' * $1
      `, [period === "24h" ? 24 : period === "7d" ? 168 : 720]);

      // Get error log count
      const errorCount = await client.query(`
        SELECT COUNT(*) as count
        FROM execution_logs
        WHERE log_level = 'ERROR'
          AND created_at > NOW() - INTERVAL '1 hour' * $1
      `, [period === "24h" ? 24 : period === "7d" ? 168 : 720]);

      // Get active traces
      const activeTraces = await client.query(`
        SELECT DISTINCT trace_id
        FROM execution_spans
        WHERE created_at > NOW() - INTERVAL '1 hour'
      `);

      return NextResponse.json({
        period,
        engagements: engagementStats.rows,
        executions: {
          total: executionStats.rows[0]?.total_executions || 0,
          successful: executionStats.rows[0]?.successful || 0,
          failed: executionStats.rows[0]?.failed || 0,
          success_rate: executionStats.rows[0]?.total_executions
            ? ((executionStats.rows[0].successful / executionStats.rows[0].total_executions) * 100).toFixed(2)
            : 0,
        },
        performance: {
          avg_duration_seconds: avgExecutionTime.rows[0]?.avg_duration || 0,
        },
        errors: errorCount.rows[0]?.count || 0,
        active_traces: activeTraces.rows.length,
        timestamp: new Date().toISOString(),
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Observability error:", error);
    return NextResponse.json(
      { error: "Failed to fetch observability data" },
      { status: 500 }
    );
  }
}