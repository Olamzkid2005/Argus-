// Database health check endpoint
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool, getPoolStats } from "@/lib/db";
import { log } from "@/lib/logger";

/**
 * GET /api/health/db
 *
 * Returns database health status
 */
export async function GET() {
  await requireAuth();
  log.api('GET', '/api/health/db');
  const startTime = Date.now();
  const checks: Record<string, unknown> = {};

  try {
    // 1. Check connection
    const client = await pool.connect();
    try {
      checks.connection = "ok";
      
      // 2. Run simple query
      const queryStart = Date.now();
      await client.query("SELECT 1");
      checks.query_time_ms = Date.now() - queryStart;
      
      // 3. Check pool stats
      const poolStats = getPoolStats();
      checks.pool = poolStats;
      checks.pool_healthy = poolStats.waitingCount < 5;
    } finally {
      client.release();
    }
    
    // 4. Check for long-running queries
    const longRunning = await pool.query(`
      SELECT pid, now() - pg_stat_activity.query_start as duration, query
      FROM pg_stat_activity 
      WHERE state = 'active' 
        AND now() - pg_stat_activity.query_start > interval '5 seconds'
    `);
    checks.long_running_queries = longRunning.rows.length;
    
    const responseTime = Date.now() - startTime;
    const isHealthy = checks.connection === "ok" && responseTime < 1000;

    log.apiEnd('GET', '/api/health/db', isHealthy ? 200 : 503, { responseTime });
    return NextResponse.json({
      status: isHealthy ? "healthy" : "degraded",
      timestamp: new Date().toISOString(),
      response_time_ms: responseTime,
      checks,
    });
  } catch (error) {
    log.error("Database health check error:", error);
    return NextResponse.json(
      {
        status: "unhealthy",
        error: "Database health check failed",
      },
      { status: 503 }
    );
  }
}