"""
Database connection management module

Provides connection pooling and session management for PostgreSQL.
"""
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
    Manages PostgreSQL connections with connection pooling.

    Provides thread-safe connection pooling and context managers for
    automatic connection cleanup.
    """

    _instance: Optional["ConnectionManager"] = None
    _pool: Optional[pool.ThreadedConnectionPool] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, min_connections: int = 1, max_connections: int = 10):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._initialized = True
        self.min_connections = min_connections
        self.max_connections = max_connections

    def initialize(self, connection_string: Optional[str] = None):
        """
        Initialize the connection pool

        Args:
            connection_string: PostgreSQL connection string
        """
        if self._pool is not None:
            return

        conn_string = connection_string or os.getenv("DATABASE_URL")

        if not conn_string:
            raise DatabaseConnectionError("No database connection string provided")

        try:
            self._pool = pool.ThreadedConnectionPool(
                self.min_connections,
                self.max_connections,
                conn_string
            )
        except psycopg2.Error as e:
            raise DatabaseConnectionError(f"Failed to create connection pool: {e}")

    def close(self):
        """Close all connections in the pool"""
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None

    @contextmanager
    def get_connection(self):
        """
        Get a connection from the pool

        Yields:
            A database connection

        Raises:
            DatabaseConnectionError: If no connection is available
        """
        if self._pool is None:
            self.initialize()

        try:
            conn = self._pool.getconn()
            try:
                yield conn
            finally:
                self._pool.putconn(conn)
        except psycopg2.Error as e:
            raise DatabaseConnectionError(f"Connection error: {e}")

    @contextmanager
    def get_cursor(self, commit: bool = True):
        """
        Get a cursor with automatic connection management

        Args:
            commit: Whether to commit the transaction on success

        Yields:
            A database cursor
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                if commit:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()


def get_connection_manager() -> ConnectionManager:
    """
    Get the singleton connection manager instance

    Returns:
        ConnectionManager instance
    """
    return ConnectionManager()


@contextmanager
def get_db_connection():
    """
    Convenience context manager for quick database access

    Yields:
        A database connection
    """
    manager = get_connection_manager()
    with manager.get_connection() as conn:
        yield conn
