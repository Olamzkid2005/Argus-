"""
Base repository class with common CRUD operations
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid


class BaseRepository:
    """
    Base repository class providing common database operations.

    Subclasses should set their table_name and id_column attributes.
    """

    table_name: str = ""
    id_column: str = "id"

    def __init__(self, connection_string: str):
        """
        Initialize repository with database connection string

        Args:
            connection_string: PostgreSQL connection string
        """
        self.connection_string = connection_string

    def _get_connection(self):
        """Get a database connection"""
        return psycopg2.connect(self.connection_string)

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
            conn.close()

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
            conn.close()

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
            conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            conn.close()

    def update_by_id(self, id: str, updates: Dict) -> Optional[Dict]:
        """
        Update a record by ID

        Args:
            id: Record ID
            updates: Dictionary of field updates

        Returns:
            Updated record dictionary or None
        """
        if not updates:
            return self.find_by_id(id)

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
            conn.commit()
            return dict(row) if row else None
        finally:
            cursor.close()
            conn.close()

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
            conn.close()
