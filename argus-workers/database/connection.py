"""
Database connection management module

Provides a thread-safe singleton connection pool for PostgreSQL.
Supports PgBouncer transaction pooling and connection monitoring.
"""
import threading
import time
import logging
import psycopg2
from psycopg2 import pool
from psycopg2.extensions import cursor as psycopg2_cursor
from contextlib import contextmanager
from typing import Optional, Dict, Any
import os

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Raised when database connection fails"""
    pass


class ConnectionManager:
    """
    Thread-safe singleton connection manager with PostgreSQL connection pooling.

    Auto-initializes on first use with DATABASE_URL from environment.
    Supports PgBouncer transaction pooling mode.
    """

    _instance: Optional["ConnectionManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._pool_lock = threading.Lock()
        self._min_connections = int(os.getenv("DB_POOL_MIN", "1"))
        self._max_connections = int(os.getenv("DB_POOL_MAX", "10"))
        self._slow_query_threshold_ms = int(os.getenv("DB_SLOW_QUERY_MS", "500"))
        self._pgbouncer_mode = os.getenv("PGBOUNCER_MODE", "session")  # session or transaction
        self._metrics: Dict[str, Any] = {
            "active_connections": 0,
            "idle_connections": 0,
            "total_queries": 0,
            "slow_queries": 0,
            "total_wait_time_ms": 0,
        }
        self._metrics_lock = threading.Lock()

    def _get_connection_string(self) -> str:
        """Get database connection string from environment with PgBouncer support"""
        conn_string = os.getenv("DATABASE_URL")
        if not conn_string:
            raise DatabaseConnectionError("DATABASE_URL environment variable not set")
        
        # Configure for PgBouncer if detected
        if "pgbouncer" in conn_string or os.getenv("USE_PGBOUNCER", "false").lower() == "true":
            # In transaction mode, we must avoid session-level features
            if self._pgbouncer_mode == "transaction":
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
                            self._min_connections,
                            self._max_connections,
                            conn_string
                        )
                        logger.info(
                            f"Database pool initialized (min={self._min_connections}, "
                            f"max={self._max_connections}, pgbouncer_mode={self._pgbouncer_mode})"
                        )
                    except psycopg2.Error as e:
                        raise DatabaseConnectionError(f"Failed to create connection pool: {e}")
        return self._pool

    def get_pool_metrics(self) -> Dict[str, Any]:
        """Get current connection pool metrics"""
        with self._metrics_lock:
            metrics = self._metrics.copy()
        
        if self._pool:
            # psycopg2 pool doesn't expose internal state directly,
            # but we can estimate from our tracking
            metrics["max_connections"] = self._max_connections
            metrics["min_connections"] = self._min_connections
        
        return metrics

    def get_connection(self):
        """
        Get a connection from the pool (thread-safe).

        Yields:
            A database connection

        Note: Always release the connection back using conn.putconn() or use the
        context manager below.
        """
        wait_start = time.time()
        pool_instance = self._ensure_pool()
        try:
            conn = pool_instance.getconn()
            wait_time = (time.time() - wait_start) * 1000
            
            with self._metrics_lock:
                self._metrics["active_connections"] += 1
                self._metrics["total_wait_time_ms"] += wait_time
            
            # Log slow connection acquisition
            if wait_time > self._slow_query_threshold_ms:
                logger.warning(f"Slow connection acquisition: {wait_time:.1f}ms")
            
            return conn
        except psycopg2.Error as e:
            raise DatabaseConnectionError(f"Connection error: {e}")

    def release_connection(self, conn):
        """Release a connection back to the pool"""
        if self._pool:
            self._pool.putconn(conn)
            with self._metrics_lock:
                self._metrics["active_connections"] = max(0, self._metrics["active_connections"] - 1)

    @contextmanager
    def connection(self, org_id: Optional[str] = None):
        """
        Context manager for automatic connection lifecycle.

        Args:
            org_id: Optional organization ID for tenant context setting

        Usage:
            with db.connection() as conn:
                cursor = conn.cursor()
                ...
        """
        conn = self.get_connection()
        try:
            # Set tenant context if org_id provided and not in transaction pooling mode
            if org_id and self._pgbouncer_mode != "transaction":
                try:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT set_tenant_context(%s)", (org_id,))
                except Exception:
                    pass  # Function may not exist yet
            
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.release_connection(conn)

    @contextmanager
    def cursor(self, commit: bool = True, org_id: Optional[str] = None):
        """
        Context manager for automatic cursor and connection lifecycle.

        Args:
            commit: Whether to commit on success
            org_id: Optional organization ID for tenant context

        Usage:
            with db.cursor() as cursor:
                cursor.execute("SELECT ...")
                rows = cursor.fetchall()
        """
        with self.connection(org_id=org_id) as conn:
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


class SlowQueryCursor(psycopg2_cursor):
    """Cursor that logs slow queries"""
    
    def execute(self, query, vars=None):
        start = time.time()
        try:
            return super().execute(query, vars)
        finally:
            elapsed_ms = (time.time() - start) * 1000
            if elapsed_ms > 500:
                logger.warning(f"Slow query ({elapsed_ms:.1f}ms): {query[:200]}")


# Singleton instance
_db: Optional[ConnectionManager] = None


def get_db() -> ConnectionManager:
    """Get the singleton database connection manager"""
    global _db
    if _db is None:
        _db = ConnectionManager()
    return _db


@contextmanager
def db_connection(org_id: Optional[str] = None):
    """Convenience context manager for database connections"""
    manager = get_db()
    with manager.connection(org_id=org_id) as conn:
        yield conn


@contextmanager
def db_cursor(commit: bool = True, org_id: Optional[str] = None):
    """Convenience context manager for database cursors"""
    manager = get_db()
    with manager.cursor(commit=commit, org_id=org_id) as cursor:
        yield cursor
