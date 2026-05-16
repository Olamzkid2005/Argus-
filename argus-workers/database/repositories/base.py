"""
Base repository class with common CRUD operations

Uses the shared connection pool from database/connection.py.
Supports passing an external connection for transaction support.
"""

import logging
import time
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from database.connection import get_db

# Column allowlists per table - prevents SQL injection in update_by_id
ALLOWED_COLUMNS = {
    "engagements": [
        "status",
        "updated_at",
        "completed_at",
        "target_url",
        "authorization",
        "authorized_scope",
        "rate_limit_config",
    ],
    "users": ["name", "role", "updated_at", "last_login_at"],
    "findings": ["verified", "fp_likelihood", "updated_at", "severity"],
    "loop_budgets": [
        "current_cycles",
        "current_depth",
        "updated_at",
        "max_cycles",
        "max_depth",
    ],
    "engagement_states": ["from_state", "to_state", "reason"],
    "job_states": [
        "status",
        "worker_id",
        "error_message",
        "started_at",
        "completed_at",
    ],
}

# Cache for schema columns with TTL (300s) — auto-renews after migrations
_schema_cache: dict[str, list[str]] = {}
_schema_cache_timestamps: dict[str, float] = {}
_SCHEMA_CACHE_TTL = 300.0  # 5 minutes


def _get_table_columns(table_name: str) -> list[str]:
    """
    Get actual column names from database schema.
    Uses cache to avoid repeated introspection.

    Args:
        table_name: Name of the table

    Returns:
        List of column names
    """
    import time as _time
    if table_name in _schema_cache:
        # Check TTL to pick up schema changes from migrations
        cached_at = _schema_cache_timestamps.get(table_name, 0)
        if _time.time() - cached_at < _SCHEMA_CACHE_TTL:
            return _schema_cache[table_name]
        # TTL expired — fall through to re-fetch

    try:
        conn = get_db().get_connection()
        cursor = conn.cursor()

        try:
            # Query information_schema for column names
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
                AND table_schema = 'public'
            """,
                (table_name,),
            )

            columns = [row[0] for row in cursor.fetchall()]
            _schema_cache[table_name] = columns
            _schema_cache_timestamps[table_name] = _time.time()
            return columns
        finally:
            cursor.close()
            get_db().release_connection(conn)
    except Exception:
        # Fall back to allowlist if schema introspection fails
        return ALLOWED_COLUMNS.get(table_name, [])


def validate_columns(table_name: str, columns: list[str]) -> list[str]:
    """
    Validate columns against database schema.

    This implements 7.5 - validates column names against actual schema
    rather than just a static allowlist, preventing SQL injection via
    column name manipulation.

    Args:
        table_name: Name of the table
        columns: List of column names to validate

    Returns:
        List of valid columns

    Raises:
        ValueError: If any columns are not in the schema
    """
    # Get valid columns from schema
    valid_columns = _get_table_columns(table_name)

    if not valid_columns:
        # Fall back to allowlist validation
        allowed = ALLOWED_COLUMNS.get(table_name, [])
        if not allowed:
            raise ValueError(f"No column validation available for table {table_name}")

        unauthorized = [c for c in columns if c not in allowed]
        if unauthorized:
            raise ValueError(f"Unauthorized columns: {unauthorized}")
        return columns

    # Validate against schema
    invalid = [c for c in columns if c not in valid_columns]
    if invalid:
        raise ValueError(f"Invalid columns for table {table_name}: {invalid}")

    return columns


class BaseRepository:
    """
    Base repository class providing common database operations.

    Subclasses should set their table_name and id_column attributes.
    Supports passing an external connection for transaction support.
    """

    table_name: str = ""
    id_column: str = "id"

    def __init__(self, connection: psycopg2.extensions.connection | str | None = None):
        """
        Initialize repository.

        Args:
            connection: Optional external connection (or connection string) for transaction support.
                       If not provided, uses the shared connection pool.
                       NOTE: If a string URL is passed, a new connection is created every time
                       _get_connection() is called and should be managed externally.
        """
        self._external_conn = connection

    def _get_connection(self, org_id: str | None = None):
        """Get a database connection (external or from pool)"""
        if self._external_conn:
            if isinstance(self._external_conn, str):
                # String connection — create a fresh connection each time.
                # These are NOT returned to the pool; the caller must close them.
                return psycopg2.connect(self._external_conn)
            # Otherwise assume it's a connection object
            return self._external_conn
        return get_db().get_connection()

    def _release_connection(self, conn):
        """Release connection back to pool (skip if external)"""
        if conn and not self._external_conn:
            get_db().release_connection(conn)

    def _to_dict(self, row: Any, cursor=None) -> dict | None:
        """Convert row to dictionary using cursor description"""
        if row is None:
            return None

        if cursor is not None:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row, strict=False))

        if hasattr(row, "_asdict"):
            return row._asdict()

        return dict(row)

    def _log_query_time(self, query: str, start_time: float, rows: int = 0):
        """Log slow queries for performance monitoring"""
        elapsed_ms = (time.time() - start_time) * 1000
        if elapsed_ms > 500:
            logging.getLogger(__name__).warning(
                f"Slow query ({elapsed_ms:.1f}ms, {rows} rows): {query[:200]}"
            )

    def find_by_id(self, id: str) -> dict | None:
        """
        Find a record by ID

        Args:
            id: Record ID

        Returns:
            Dictionary of the record or None
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        start = time.time()

        try:
            query = f"SELECT * FROM {self.table_name} WHERE {self.id_column} = %s"
            cursor.execute(query, (id,))
            row = cursor.fetchone()
            self._log_query_time(query, start, 1 if row else 0)
            return dict(row) if row else None
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def find_all(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """
        Find all records with pagination

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip

        Returns:
            List of record dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        start = time.time()

        try:
            query = f"SELECT * FROM {self.table_name} ORDER BY created_at DESC LIMIT %s OFFSET %s"
            cursor.execute(query, (limit, offset))
            rows = cursor.fetchall()
            self._log_query_time(query, start, len(rows))
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def delete_by_id(self, id: str) -> bool:
        """
        Delete a record by ID

        Args:
            id: Record ID

        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"DELETE FROM {self.table_name} WHERE {self.id_column} = %s", (id,)
            )
            if not self._external_conn:
                conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def update_by_id(self, id: str, updates: dict) -> dict | None:
        """
        Update a record by ID

        Args:
            id: Record ID
            updates: Dictionary of field updates (validated against schema)

        Returns:
            Updated record dictionary or None

        Raises:
            ValueError: If updates contain unauthorized columns
        """
        if not updates:
            return self.find_by_id(id)

        # Validate columns against database schema (prevents SQL injection)
        # This uses schema introspection with fallback to allowlist
        try:
            validate_columns(self.table_name, list(updates.keys()))
        except ValueError:
            # Fall back to allowlist validation
            allowed = ALLOWED_COLUMNS.get(self.table_name, [])
            if not allowed:
                raise ValueError(
                    f"No column allowlist defined for table {self.table_name}"
                ) from None

            unauthorized = [k for k in updates if k not in allowed]
            if unauthorized:
                raise

        # Don't force updated_at if caller provides it
        if "updated_at" not in updates:
            set_clauses = [f"{key} = %s" for key in updates] + ["updated_at = NOW()"]
        else:
            set_clauses = [f"{key} = %s" for key in updates]
        values = list(updates.values()) + [id]

        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            query = f"""
                UPDATE {self.table_name}
                SET {", ".join(set_clauses)}
                WHERE {self.id_column} = %s
                RETURNING *
            """
            cursor.execute(query, values)
            row = cursor.fetchone()
            if not self._external_conn:
                conn.commit()
            return dict(row) if row else None
        except Exception:
            if not self._external_conn and conn:
                conn.rollback()
            raise
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def count(self) -> int:
        """
        Count total records

        Returns:
            Total number of records
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        start = time.time()

        try:
            query = f"SELECT COUNT(*) FROM {self.table_name}"
            cursor.execute(query)
            result = cursor.fetchone()[0]
            self._log_query_time(query, start)
            return result
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)
