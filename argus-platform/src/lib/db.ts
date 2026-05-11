import { Pool, PoolConfig } from "pg";
import { log } from "@/lib/logger";

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
 *
 * Uses globalThis to survive Next.js hot-reload cycles in development.
 * Without this, every hot reload creates a new Pool, leaking connections
 * (observed: 123 idle connections vs pool max of 20).
 */
const globalForPool = globalThis as unknown as { __pgPool?: Pool };
export const pool = globalForPool.__pgPool ?? (globalForPool.__pgPool = new Pool(poolConfig));

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

/**
 * N+1 alert event structure
 */
export type N1AlertEvent = {
  queryText: string;
  similarCount: number;
  threshold: number;
  windowMs: number;
  timestamp: number;
};

const n1AlertBuffer: N1AlertEvent[] = [];
const MAX_N1_ALERTS = 50;

let lastN1Detected: { queryText: string; timestamp: number } | null = null;

pool.on("error", (err) => {
  log.db.poolError(err);
});

pool.on("connect", () => {
  log.db.query("Pool client connected");
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
 * Get N+1 detection metrics
 */
export function getN1Metrics() {
  return {
    warningCount: queryMetrics.n1WarningCount,
    lastDetected: lastN1Detected,
  };
}

/**
 * Get recent N+1 alerts from the in-memory buffer
 */
export function getRecentN1Alerts(): N1AlertEvent[] {
  return n1AlertBuffer.slice();
}

/**
 * Detect potential N+1 query patterns
 */
function detectN1Query(
  queryText: string,
  onN1Detected?: (alert: N1AlertEvent) => void
): void {
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

    const alert: N1AlertEvent = {
      queryText,
      similarCount,
      threshold: N1_THRESHOLD,
      windowMs: N1_DETECTION_WINDOW_MS,
      timestamp: now,
    };

    lastN1Detected = { queryText, timestamp: now };

    n1AlertBuffer.push(alert);
    if (n1AlertBuffer.length > MAX_N1_ALERTS) {
      n1AlertBuffer.shift();
    }

    log.warn("DB", `N+1 query pattern detected (${similarCount} similar queries in ${N1_DETECTION_WINDOW_MS}ms): ${queryText.substring(0, 100)}`);

    if (onN1Detected) {
      onN1Detected(alert);
    }
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
  options?: { orgId?: string; skipN1Detection?: boolean; onN1Detected?: (alert: N1AlertEvent) => void }
): Promise<{ rows: T[]; rowCount: number }> {
  const start = performance.now();

  let client;
  try {
    client = await pool.connect();
  } catch (error) {
    log.db.connectionError(error);
    throw error;
  }
  try {
    // Set tenant context if orgId provided and not in PgBouncer transaction mode
    if (options?.orgId && process.env.PGBOUNCER_MODE !== "transaction") {
      try {
        await client.query("SELECT set_tenant_context($1)", [options.orgId]);
      } catch (error) {
        log.db.queryError("set_tenant_context", error);
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
      log.db.slowQuery(text, duration);
    }

    if (!options?.skipN1Detection) {
      detectN1Query(text, options?.onN1Detected);
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
  let client;
  try {
    client = await pool.connect();
  } catch (error) {
    log.db.connectionError(error);
    throw error;
  }
  try {
    if (options?.orgId && process.env.PGBOUNCER_MODE !== "transaction") {
      try {
        await client.query("SELECT set_tenant_context($1)", [options.orgId]);
      } catch (error) {
        log.db.queryError("set_tenant_context", error);
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
  } catch (error) {
    log.db.queryError("set_tenant_context", error);
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
  } catch (error) {
    log.db.queryError("reset_tenant_context", error);
  }
}