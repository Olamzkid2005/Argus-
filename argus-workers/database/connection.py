"""
Database connection management module

Provides a thread-safe singleton connection pool for PostgreSQL.
Supports PgBouncer transaction pooling and connection monitoring.
"""

import logging
import os
import random
import threading
import time
from contextlib import contextmanager
from typing import Any, Optional

import psycopg2
from psycopg2 import pool

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Raised when database connection fails"""

    pass


class ConnectionManager:
    """
    Thread-safe singleton connection manager with PostgreSQL connection pooling.

    Auto-initializes on first use with DATABASE_URL from environment.
    Supports PgBouncer transaction pooling mode.

    Security features:
    - statement_timeout enforced on every connection to prevent runaway queries
    - SSL mode configurable via DB_SSLMODE env var (default: prefer)
    - Connection acquisition timeout to prevent worker process stalls
    """

    _instance: Optional["ConnectionManager"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._instance_lock:
            if self._initialized:
                return
            self._initialized = True
            self._pool: pool.ThreadedConnectionPool | None = None
            self._pool_lock = threading.Lock()
        self._min_connections = int(os.getenv("DB_POOL_MIN", "2"))
        self._max_connections = int(os.getenv("DB_POOL_MAX", "20"))
        self._slow_query_threshold_ms = int(os.getenv("DB_SLOW_QUERY_MS", "500"))
        self._statement_timeout_ms = int(
            os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000")
        )  # 30s default
        self._pgbouncer_mode = os.getenv(
            "PGBOUNCER_MODE", "session"
        )  # session or transaction
        self._ssl_mode = os.getenv(
            "DB_SSLMODE", "prefer"
        )  # prefer, require, verify-ca, verify-full
        self._metrics: dict[str, Any] = {
            "active_connections": 0,
            "idle_connections": 0,
            "total_queries": 0,
            "slow_queries": 0,
            "total_wait_time_ms": 0,
        }
        self._metrics_lock = threading.Lock()
        # Condition variable for signaling connection availability (B.03 fix)
        self._pool_cond = threading.Condition()

    def _get_connection_string(self) -> str:
        """Get database connection string from environment with PgBouncer support"""
        conn_string = os.getenv("DATABASE_URL")
        if not conn_string:
            raise DatabaseConnectionError("DATABASE_URL environment variable not set")

        # Add SSL mode parameter if not already in connection string
        if "sslmode" not in conn_string:
            separator = "&" if "?" in conn_string else "?"
            ssl_params = f"sslmode={self._ssl_mode}"
            conn_string += f"{separator}{ssl_params}"

        # Configure for PgBouncer if detected
        if (
            "pgbouncer" in conn_string
            or os.getenv("USE_PGBOUNCER", "false").lower() == "true"
        ) and self._pgbouncer_mode == "transaction":
            # Add options to disable session features
            if "?" not in conn_string:
                conn_string += "?"
            else:
                conn_string += "&"
            conn_string += "options=-c%20statement_timeout%3D0"

        return conn_string

    def _ensure_pool(self) -> pool.ThreadedConnectionPool:
        """Ensure the connection pool is initialized (thread-safe)"""
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    try:
                        conn_string = self._get_connection_string()
                        self._pool = pool.ThreadedConnectionPool(
                            self._min_connections, self._max_connections, conn_string
                        )
                        logger.info(
                            "Database pool initialized (min=%d, "
                            "max=%d, pgbouncer_mode=%s, "
                            "ssl_mode=%s, "
                            "statement_timeout=%dms)",
                            self._min_connections,
                            self._max_connections,
                            self._pgbouncer_mode,
                            self._ssl_mode,
                            self._statement_timeout_ms,
                        )
                    except psycopg2.Error as e:
                        raise DatabaseConnectionError(
                            f"Failed to create connection pool: {e}"
                        ) from e
        return self._pool

    def get_pool_metrics(self) -> dict[str, Any]:
        """Get current connection pool metrics"""
        with self._metrics_lock:
            metrics = self._metrics.copy()

        if self._pool:
            # psycopg2 pool doesn't expose internal state directly,
            # but we can estimate from our tracking
            metrics["max_connections"] = self._max_connections
            metrics["min_connections"] = self._min_connections

        return metrics

    def get_connection(self, timeout: int = 30):
        """
        Get a connection from the pool (thread-safe).

        Args:
            timeout: Maximum seconds to wait for a connection (0 = block indefinitely).
                     Default 30s to prevent worker process stalls.

        Returns:
            A database connection

        Note: Always release the connection back using conn.putconn() or use the
        context manager below.
        """
        wait_start = time.time()
        pool_instance = self._ensure_pool()
        try:
            # Use a condition-variable wait with exponential backoff + jitter
            # to avoid busy-wait CPU waste under high contention.
            # B.03: Replaced time.sleep() polling with threading.Condition wait.
            # B.04: Added uniform jitter to spread retries during thundering herd.
            deadline = wait_start + timeout if timeout > 0 else None
            _retry_count = 0
            while True:
                try:
                    conn = pool_instance.getconn()
                    break
                except pool.PoolError:
                    if deadline and time.time() >= deadline:
                        raise DatabaseConnectionError(
                            f"Timed out waiting for database connection "
                            f"after {timeout}s (pool max={self._max_connections})"
                        ) from None
                    _retry_count += 1
                    # Exponential backoff: 10ms, 20ms, 40ms, ... capped at 500ms
                    base_delay = min(0.01 * (2 ** (_retry_count - 1)), 0.5)
                    # Uniform jitter: [0.5 * base, 1.5 * base)
                    jitter = base_delay * (0.5 + random.random())
                    with self._pool_cond:
                        self._pool_cond.wait(timeout=jitter)
                    continue
            wait_time = (time.time() - wait_start) * 1000

            # Enforce statement_timeout on each connection
            # This prevents runaway queries from blocking the pool
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SET statement_timeout = %s", (self._statement_timeout_ms,)
                    )
            except psycopg2.Error as st_err:
                # M-v4-02: Log warning when statement_timeout can't be set.
                # Without this, the connection returns to the pool without
                # query timeout, allowing runaway queries.
                logger.warning(
                    "Failed to set statement_timeout on connection %s: %s",
                    id(conn),
                    st_err,
                )

            with self._metrics_lock:
                self._metrics["active_connections"] += 1
                self._metrics["total_wait_time_ms"] += wait_time

            # Log slow connection acquisition
            if wait_time > self._slow_query_threshold_ms:
                logger.warning("Slow connection acquisition: %.1fms", wait_time)

            return conn
        except psycopg2.Error as e:
            raise DatabaseConnectionError(f"Connection error: {e}") from e

    def release_connection(self, conn):
        """Release a connection back to the pool (safe, never raises)"""
        if self._pool and conn:
            try:
                self._pool.putconn(conn)
                # Notify any thread waiting on the condition variable (B.03 fix)
                with self._pool_cond:
                    self._pool_cond.notify_all()
            except Exception as e:
                logger.error("Failed to release connection back to pool: %s", e)
            with self._metrics_lock:
                self._metrics["active_connections"] = max(
                    0, self._metrics["active_connections"] - 1
                )

    @contextmanager
    def connection(self, commit: bool = True, org_id: str | None = None):
        """
        Context manager for automatic connection lifecycle.

        Args:
            commit: Whether to commit on success (default: True).
                    Set to False if you manage transactions manually.
            org_id: Optional organization ID for tenant context setting

        Usage:
            with db.connection() as conn:
                cursor = conn.cursor()
                ...

            with db.connection(commit=False) as conn:
                conn.execute(...)
                conn.commit()  # manual control
        """
        conn = self.get_connection()
        try:
            if org_id and self._pgbouncer_mode != "transaction":
                try:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT set_tenant_context(%s)", (org_id,))
                except Exception as ctx_e:
                    logger.warning(
                        "Failed to set tenant context for org %s: %s — "
                        "data isolation cannot be guaranteed without tenant context. "
                        "Ensure set_tenant_context() function exists in the database.",
                        org_id,
                        ctx_e,
                    )

            yield conn
            if commit:
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception as rb_err:
                logger.warning("Rollback failed: %s", rb_err)
            raise
        finally:
            # Reset tenant context to prevent cross-org data leakage
            # on connection reuse (C-v3-03)
            if org_id:
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT set_tenant_context('00000000-0000-0000-0000-000000000000')"
                        )
                except Exception as ctx_e:
                    logger.debug("Failed to reset tenant context: %s", ctx_e)
            self.release_connection(conn)

    @contextmanager
    def cursor(self, commit: bool = True, org_id: str | None = None):
        """
        Context manager for automatic cursor and connection lifecycle.

        Args:
            commit: Whether to commit on success
            org_id: Optional organization ID for tenant context

        Usage:
            with db.cursor() as cursor:
                cursor.execute("SELECT ...")
                rows = cursor.fetchall()

            with db.cursor(commit=False) as cursor:
                cursor.execute("UPDATE ...")
                conn.commit()  # manual control
        """
        with self.connection(commit=commit, org_id=org_id) as conn:
            cursor = conn.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

    def close(self):
        """Close all connections in the pool"""
        with self._pool_lock:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None
                logger.info("Database pool closed")


# Singleton instance
_db: ConnectionManager | None = None
_db_lock = threading.Lock()


def get_db() -> ConnectionManager:
    """Get the singleton database connection manager (thread-safe)"""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                _db = ConnectionManager()
    return _db


@contextmanager
def db_connection(org_id: str | None = None):
    """Convenience context manager for database connections"""
    manager = get_db()
    with manager.connection(org_id=org_id) as conn:
        yield conn


@contextmanager
def db_cursor(commit: bool = True, org_id: str | None = None):
    """Convenience context manager for database cursors"""
    manager = get_db()
    with manager.cursor(commit=commit, org_id=org_id) as cursor:
        yield cursor


def connect(connection_string: str | None = None) -> psycopg2.extensions.connection:
    """
    Standardized database connection helper.

    Prefer using get_db().get_connection() for pool connections.
    This helper is for one-off connections when the pool is not available.

    Args:
        connection_string: Optional connection string. Defaults to DATABASE_URL env var.

    Returns:
        psycopg2 connection object

    Raises:
        DatabaseConnectionError: If connection string is missing or connection fails
    """
    conn_string = connection_string or os.getenv("DATABASE_URL")
    if not conn_string:
        raise DatabaseConnectionError("DATABASE_URL environment variable not set")
    try:
        return psycopg2.connect(conn_string)
    except psycopg2.Error as e:
        raise DatabaseConnectionError(f"Failed to connect to database: {e}") from e
