import { Pool, PoolConfig } from "pg";

/**
 * Database connection pool configuration
 * Optimized for production use with proper timeouts and error handling
 * Supports PgBouncer transaction pooling
 */
const poolConfig: PoolConfig = {
  connectionString: process.env.DATABASE_URL,
  max: parseInt(process.env.DB_POOL_MAX || "20", 10),
  min: parseInt(process.env.DB_POOL_MIN || "2", 10),
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
  maxUses: 10000,
  allowExitOnIdle: false,
  // PgBouncer compatibility: disable prepared statements in transaction mode
  ...(process.env.PGBOUNCER_MODE === "transaction"
    ? { prepare: false }
    : {}),
};

/**
 * Shared PostgreSQL connection pool.
 * Single instance used across all API routes to avoid connection exhaustion.
 */
export const pool = new Pool(poolConfig);

/**
 * Track pool health and query metrics
 */
const queryMetrics = {
  totalQueries: 0,
  slowQueries: 0,
  totalTimeMs: 0,
  n1WarningCount: 0,
};

const recentQueries: Array<{ text: string; duration: number; timestamp: number }> = [];
const N1_DETECTION_WINDOW_MS = 5000;
const N1_THRESHOLD = 5;

pool.on("error", (err) => {
  console.error("Unexpected database pool error:", err);
});

pool.on("connect", () => {
  console.log("Database client connected");
});

/**
 * Get pool statistics
 */
export function getPoolStats() {
  return {
    totalCount: pool.totalCount,
    idleCount: pool.idleCount,
    waitingCount: pool.waitingCount,
    maxConnections: poolConfig.max,
    minConnections: poolConfig.min,
    queryMetrics: { ...queryMetrics },
  };
}

/**
 * Detect potential N+1 query patterns
 */
function detectN1Query(queryText: string): void {
  const now = Date.now();
  const windowStart = now - N1_DETECTION_WINDOW_MS;

  // Clean old queries outside window
  while (recentQueries.length > 0 && recentQueries[0].timestamp < windowStart) {
    recentQueries.shift();
  }

  // Check for repeated similar queries
  const normalized = queryText.replace(/\$\d+/g, "?").toLowerCase().trim();
  const similarCount = recentQueries.filter(
    (q) =>
      q.text.replace(/\$\d+/g, "?").toLowerCase().trim() === normalized
  ).length;

  if (similarCount >= N1_THRESHOLD) {
    queryMetrics.n1WarningCount++;
    console.warn(
      `N+1 query pattern detected (${similarCount} similar queries in ${N1_DETECTION_WINDOW_MS}ms): ${queryText.substring(0, 100)}`
    );
  }

  recentQueries.push({ text: queryText, duration: 0, timestamp: now });
}

/**
 * Execute a query with automatic connection management and performance monitoring.
 * The pool handles connection lifecycle — acquire from pool, release back when done.
 */
export async function query<T = unknown>(
  text: string,
  params?: unknown[],
  options?: { orgId?: string; skipN1Detection?: boolean }
): Promise<{ rows: T[]; rowCount: number }> {
  const start = performance.now();

  const client = await pool.connect();
  try {
    // Set tenant context if orgId provided and not in PgBouncer transaction mode
    if (options?.orgId && process.env.PGBOUNCER_MODE !== "transaction") {
      try {
        await client.query("SELECT set_tenant_context($1)", [options.orgId]);
      } catch {
        // Function may not exist yet
      }
    }

    const result = await client.query(text, params);
    return { rows: result.rows as T[], rowCount: result.rowCount ?? 0 };
  } finally {
    client.release();

    const duration = performance.now() - start;
    queryMetrics.totalQueries++;
    queryMetrics.totalTimeMs += duration;

    if (duration > 500) {
      queryMetrics.slowQueries++;
      console.warn(`Slow query (${duration.toFixed(1)}ms): ${text.substring(0, 200)}`);
    }

    if (!options?.skipN1Detection) {
      detectN1Query(text);
    }
  }
}

/**
 * Execute a query with a client from the pool
 * Use this when you need transaction support
 */
export async function withClient<T>(
  callback: (client: Pool) => Promise<T>,
  options?: { orgId?: string }
): Promise<T> {
  const client = await pool.connect();
  try {
    if (options?.orgId && process.env.PGBOUNCER_MODE !== "transaction") {
      try {
        await client.query("SELECT set_tenant_context($1)", [options.orgId]);
      } catch {
        // Function may not exist yet
      }
    }
    return await callback(client as unknown as Pool);
  } finally {
    client.release();
  }
}

/**
 * Set tenant context for the current connection
 */
export async function setTenantContext(
  client: InstanceType<typeof Pool>,
  orgId: string
): Promise<void> {
  if (process.env.PGBOUNCER_MODE === "transaction") return;
  try {
    await client.query("SELECT set_tenant_context($1)", [orgId]);
  } catch {
    // Function may not exist yet
  }
}

/**
 * Reset tenant context
 */
export async function resetTenantContext(
  client: InstanceType<typeof Pool>
): Promise<void> {
  if (process.env.PGBOUNCER_MODE === "transaction") return;
  try {
    await client.query("SELECT reset_tenant_context()");
  } catch {
    // Function may not exist yet
  }
}