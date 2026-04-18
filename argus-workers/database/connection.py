"""
Database connection management module

Provides a thread-safe singleton connection pool for PostgreSQL.
"""
import threading
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from typing import Optional
import os


class DatabaseConnectionError(Exception):
    """Raised when database connection fails"""
    pass


class ConnectionManager:
    """
    Thread-safe singleton connection manager with PostgreSQL connection pooling.

    Auto-initializes on first use with DATABASE_URL from environment.
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
        self._min_connections = 1
        self._max_connections = 10

    def _get_connection_string(self) -> str:
        """Get database connection string from environment"""
        conn_string = os.getenv("DATABASE_URL")
        if not conn_string:
            raise DatabaseConnectionError("DATABASE_URL environment variable not set")
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
                    except psycopg2.Error as e:
                        raise DatabaseConnectionError(f"Failed to create connection pool: {e}")
        return self._pool

    def get_connection(self):
        """
        Get a connection from the pool (thread-safe).

        Yields:
            A database connection

        Note: Always release the connection back using conn.putconn() or use the
        context manager below.
        """
        pool_instance = self._ensure_pool()
        try:
            conn = pool_instance.getconn()
            return conn
        except psycopg2.Error as e:
            raise DatabaseConnectionError(f"Connection error: {e}")

    def release_connection(self, conn):
        """Release a connection back to the pool"""
        if self._pool:
            self._pool.putconn(conn)

    @contextmanager
    def connection(self):
        """
        Context manager for automatic connection lifecycle.

        Usage:
            with db.connection() as conn:
                cursor = conn.cursor()
                ...
        """
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.release_connection(conn)

    @contextmanager
    def cursor(self, commit: bool = True):
        """
        Context manager for automatic cursor and connection lifecycle.

        Args:
            commit: Whether to commit on success

        Usage:
            with db.cursor() as cursor:
                cursor.execute("SELECT ...")
                rows = cursor.fetchall()
        """
        with self.connection() as conn:
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


# Singleton instance
_db: Optional[ConnectionManager] = None


def get_db() -> ConnectionManager:
    """Get the singleton database connection manager"""
    global _db
    if _db is None:
        _db = ConnectionManager()
    return _db


@contextmanager
def db_connection():
    """Convenience context manager for database connections"""
    manager = get_db()
    with manager.connection() as conn:
        yield conn


@contextmanager
def db_cursor(commit: bool = True):
    """Convenience context manager for database cursors"""
    manager = get_db()
    with manager.cursor(commit=commit) as cursor:
        yield cursor
