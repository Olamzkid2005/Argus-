import { Pool } from "pg";

/**
 * Shared PostgreSQL connection pool.
 * Single instance used across all API routes to avoid connection exhaustion.
 */
export const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 20, // explicit cap, though pg defaults to 10
});

/**
 * Execute a query with automatic connection management.
 * The pool handles connection lifecycle — acquire from pool, release back when done.
 */
export async function query<T = unknown>(
  text: string,
  params?: unknown[]
): Promise<{ rows: T[]; rowCount: number }> {
  const result = await pool.query(text, params);
  return { rows: result.rows as T[], rowCount: result.rowCount ?? 0 };
}
