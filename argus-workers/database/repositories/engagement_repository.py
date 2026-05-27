"""
Engagement repository for database operations on engagements
"""

from psycopg2.extras import Json, RealDictCursor

from database.repositories.base import BaseRepository


class EngagementRepository(BaseRepository):
    """
    Repository for engagements

    Provides specialized queries for engagement data access.
    """

    table_name = "engagements"
    id_column = "id"

    def create(self, engagement_data: dict) -> dict:
        """
        Create a new engagement

        Args:
            engagement_data: Dictionary with engagement data

        Returns:
            Created engagement dictionary
        """
        import uuid

        with self.db_operation(commit=True, cursor_factory=RealDictCursor) as (conn, cursor):
            engagement_id = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO engagements (
                    id, org_id, target_url, authorization_proof,
                    authorized_scope, status, created_by, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                RETURNING *
                """,
                (
                    engagement_id,
                    engagement_data.get("org_id"),
                    engagement_data.get("target_url"),
                    engagement_data.get("authorization_proof") or engagement_data.get("authorization"),
                    Json(engagement_data.get("authorized_scope", {})),
                    engagement_data.get("status", "created"),
                    engagement_data.get("created_by"),
                )
            )
            row = cursor.fetchone()
            return dict(row)

    def find_by_org(self, org_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        """
        Find all engagements for an organization with pagination.

        Args:
            org_id: Organization ID
            limit: Maximum number of records
            offset: Number of records to skip

        Returns:
            List of engagement dictionaries
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            # Use JOINs instead of subqueries to avoid N+1 queries
            cursor.execute(
                """
                SELECT
                    e.*,
                    u.email as created_by_email,
                    COALESCE(f.findings_count, 0) as findings_count
                FROM engagements e
                LEFT JOIN users u ON e.created_by = u.id
                LEFT JOIN (
                    SELECT engagement_id, COUNT(*) as findings_count
                    FROM findings
                    GROUP BY engagement_id
                ) f ON e.id = f.engagement_id
                WHERE e.org_id = %s
                ORDER BY e.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (org_id, limit, offset)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def find_active_by_org(self, org_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        """
        Find active engagements for an organization

        Args:
            org_id: Organization ID
            limit: Maximum number of records
            offset: Number of records to skip

        Returns:
            List of active engagement dictionaries
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            # Use JOINs instead of subqueries to avoid N+1 queries
            cursor.execute(
                """
                SELECT
                    e.*,
                    u.email as created_by_email,
                    COALESCE(f.findings_count, 0) as findings_count
                FROM engagements e
                LEFT JOIN users u ON e.created_by = u.id
                LEFT JOIN (
                    SELECT engagement_id, COUNT(*) as findings_count
                    FROM findings
                    GROUP BY engagement_id
                ) f ON e.id = f.engagement_id
                WHERE e.org_id = %s AND e.status NOT IN ('complete', 'failed')
                ORDER BY e.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (org_id, limit, offset)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def update_status(self, engagement_id: str, status: str) -> dict | None:
        """
        Update engagement status

        Args:
            engagement_id: Engagement ID
            status: New status

        Returns:
            Updated engagement dictionary or None
        """
        return self.update_by_id(engagement_id, {"status": status})

    def find_by_status(self, status: str, org_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        """
        Find engagements by status, scoped to an organization.

        Args:
            status: Status to filter by
            org_id: Organization ID (required — prevents cross-org data leak, H-v3-08)
            limit: Maximum number of records
            offset: Number of records to skip

        Returns:
            List of engagement dictionaries
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                """
                SELECT * FROM engagements
                WHERE status = %s AND org_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (status, org_id, limit, offset)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
