import { Pool, PoolConfig } from "pg";

/**
 * Database connection pool configuration
 * Optimized for production use with proper timeouts and error handling
 */
const poolConfig: PoolConfig = {
  connectionString: process.env.DATABASE_URL,
  max: 20, // Maximum number of connections
  min: 2, // Minimum number of connections to keep
  idleTimeoutMillis: 30000, // Close idle connections after 30s
  connectionTimeoutMillis: 5000, // Return error after 5s if connection can't be established
  maxUses: 10000, // Maximum number of uses per connection before recycling
  allowExitOnIdle: false, // Don't force exit on idle (for serverless)
};

/**
 * Shared PostgreSQL connection pool.
 * Single instance used across all API routes to avoid connection exhaustion.
 */
export const pool = new Pool(poolConfig);

/**
 * Track pool health
 */
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
  };
}

/**
 * Execute a query with automatic connection management.
 * The pool handles connection lifecycle — acquire from pool, release back when done.
 */
export async function query<T = unknown>(
  text: string,
  params?: unknown[],
): Promise<{ rows: T[]; rowCount: number }> {
  const result = await pool.query(text, params);
  return { rows: result.rows as T[], rowCount: result.rowCount ?? 0 };
}

/**
 * Execute a query with a client from the pool
 * Use this when you need transaction support
 */
export async function withClient<T>(
  callback: (client: Pool) => Promise<T>
): Promise<T> {
  const client = await pool.connect();
  try {
    return await callback(client as unknown as Pool);
  } finally {
    client.release();
  }
}