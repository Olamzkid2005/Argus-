"""
Base repository class with common CRUD operations

Uses the shared connection pool from database/connection.py.
Supports passing an external connection for transaction support.
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import uuid

from database.connection import get_db

# Column allowlists per table - prevents SQL injection in update_by_id
ALLOWED_COLUMNS = {
    "engagements": ["status", "updated_at", "completed_at", "target_url", "authorization",
                    "authorized_scope", "rate_limit_config"],
    "users": ["name", "role", "updated_at", "last_login_at"],
    "findings": ["verified", "fp_likelihood", "updated_at", "severity"],
    "loop_budgets": ["current_cycles", "current_depth", "current_cost", "updated_at",
                     "max_cycles", "max_depth", "max_cost"],
    "engagement_states": ["from_state", "to_state", "reason"],
    "job_states": ["status", "worker_id", "error_message", "started_at", "completed_at"],
}


class BaseRepository:
    """
    Base repository class providing common database operations.

    Subclasses should set their table_name and id_column attributes.
    Supports passing an external connection for transaction support.
    """

    table_name: str = ""
    id_column: str = "id"

    def __init__(self, connection: Optional[Union[psycopg2.extensions.connection, str]] = None):
        """
        Initialize repository.

        Args:
            connection: Optional external connection (or connection string) for transaction support.
                       If not provided, uses the shared connection pool.
        """
        self._external_conn = connection

    def _get_connection(self):
        """Get a database connection (external or from pool)"""
        if self._external_conn:
            # If it's a string, create a connection from it
            if isinstance(self._external_conn, str):
                return psycopg2.connect(self._external_conn)
            # Otherwise assume it's a connection object
            return self._external_conn
        return get_db().get_connection()

    def _release_connection(self, conn):
        """Release connection back to pool (skip if external)"""
        if conn and not self._external_conn:
            get_db().release_connection(conn)

    def _to_dict(self, row: Any, cursor=None) -> Optional[Dict]:
        """Convert row to dictionary using cursor description"""
        if row is None:
            return None

        if cursor is not None:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))

        if hasattr(row, "_asdict"):
            return row._asdict()

        return dict(row)

    def find_by_id(self, id: str) -> Optional[Dict]:
        """
        Find a record by ID

        Args:
            id: Record ID

        Returns:
            Dictionary of the record or None
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                f"SELECT * FROM {self.table_name} WHERE {self.id_column} = %s",
                (id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def find_all(self, limit: int = 100, offset: int = 0) -> List[Dict]:
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

        try:
            cursor.execute(
                f"SELECT * FROM {self.table_name} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset)
            )
            rows = cursor.fetchall()
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
                f"DELETE FROM {self.table_name} WHERE {self.id_column} = %s",
                (id,)
            )
            if not self._external_conn:
                conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def update_by_id(self, id: str, updates: Dict) -> Optional[Dict]:
        """
        Update a record by ID

        Args:
            id: Record ID
            updates: Dictionary of field updates (validated against allowlist)

        Returns:
            Updated record dictionary or None

        Raises:
            ValueError: If updates contain unauthorized columns
        """
        if not updates:
            return self.find_by_id(id)

        # Validate columns against allowlist (prevents SQL injection)
        allowed = ALLOWED_COLUMNS.get(self.table_name, [])
        if not allowed:
            raise ValueError(f"No column allowlist defined for table {self.table_name}")

        unauthorized = [k for k in updates.keys() if k not in allowed]
        if unauthorized:
            raise ValueError(f"Unauthorized columns: {unauthorized}")

        set_clauses = [f"{key} = %s" for key in updates.keys()]
        values = list(updates.values()) + [id]

        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            query = f"""
                UPDATE {self.table_name}
                SET {', '.join(set_clauses)}, updated_at = NOW()
                WHERE {self.id_column} = %s
                RETURNING *
            """
            cursor.execute(query, values)
            row = cursor.fetchone()
            if not self._external_conn:
                conn.commit()
            return dict(row) if row else None
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

        try:
            cursor.execute(f"SELECT COUNT(*) FROM {self.table_name}")
            return cursor.fetchone()[0]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)
