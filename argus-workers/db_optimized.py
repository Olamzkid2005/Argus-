"""
Database optimized connection for workers

Uses connection pooling with automatic recycling
"""

import logging
import os
import warnings
from collections.abc import Generator
from contextlib import contextmanager

from psycopg2 import pool
from psycopg2.extras import RealDictCursor

warnings.warn(
    "db_optimized.py is deprecated. Use database.connection instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger(__name__)

# Database connection settings
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "argus_pentest")
DB_USER = os.getenv("DB_USER", "argus_user")
DB_PASSWORD = os.environ["DB_PASSWORD"]  # Will raise KeyError if unset

# Connection pool - lazy initialization
_connection_pool: pool.ThreadedConnectionPool | None = None


def get_connection_pool() -> pool.ThreadedConnectionPool:
    """Get or create database connection pool"""
    global _connection_pool

    if _connection_pool is None:
        logger.info("Creating database connection pool")
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            options="-c statement_timeout=30000",  # 30s query timeout
        )

    return _connection_pool


@contextmanager
def get_db_cursor() -> Generator[RealDictCursor, None, None]:
    """Get a database cursor from the pool"""
    conn = None
    cursor = None
    try:
        conn = get_connection_pool().getconn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        yield cursor
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            get_connection_pool().putconn(conn)


def close_all_connections():
    """Close all connections in the pool"""
    global _connection_pool

    if _connection_pool:
        logger.info("Closing database connections")
        _connection_pool.closeall()
        _connection_pool = None


# Health check function
def check_db_health() -> bool:
    """Check database connectivity"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
