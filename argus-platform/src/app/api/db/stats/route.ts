// Database statistics endpoint
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { getPoolStats, pool } from "@/lib/db";

/**
 * GET /api/db/stats
 *
 * Returns database statistics for monitoring
 */
export async function GET(req: Request) {
  try {
    await requireAuth();

    const client = await pool.connect();

    try {
      // Get table statistics
      const tableStats = await client.query(`
        SELECT 
          schemaname,
          tablename,
          pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
          n_live_tup as row_count,
          n_dead_tup as dead_rows,
          last_vacuum,
          last_autovacuum,
          last_analyze
        FROM pg_stat_user_tables
        WHERE schemaname = 'public'
        ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
        LIMIT 10
      `);

      // Get index statistics
      const indexStats = await client.query(`
        SELECT 
          schemaname,
          tablename,
          indexname,
          pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
          idx_scan as scans,
          idx_tup_read as tuples_read,
          idx_tup_fetch as tuples_fetched
        FROM pg_stat_user_indexes
        WHERE schemaname = 'public'
        ORDER BY idx_scan DESC
        LIMIT 10
      `);

      // Get connection pool stats
      const poolInfo = getPoolStats();

      // Get database size
      const dbSize = await client.query(`
        SELECT pg_size_pretty(pg_database_size(current_database())) as size
      `);

      return NextResponse.json({
        database: {
          size: dbSize.rows[0]?.size,
        },
        pool: {
          total: poolInfo.totalCount,
          idle: poolInfo.idleCount,
          waiting: poolInfo.waitingCount,
        },
        tables: tableStats.rows,
        indexes: indexStats.rows,
        generated_at: new Date().toISOString(),
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Get db stats error:", error);
    return NextResponse.json(
      { error: "Failed to fetch database statistics" },
      { status: 500 }
    );
  }
}