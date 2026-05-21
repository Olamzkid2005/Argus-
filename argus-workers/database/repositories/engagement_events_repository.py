"""
Engagement events repository for event sourcing operations
"""
import uuid

from psycopg2.extras import Json, RealDictCursor

from database.repositories.base import BaseRepository


class EngagementEventsRepository(BaseRepository):
    """
    Repository for engagement lifecycle events.

    Provides event sourcing operations for engagement state changes,
    scan milestones, findings discovery, and actor-tracked actions.
    """

    table_name = "engagement_events"
    id_column = "id"

    def record_event(
        self,
        engagement_id: str,
        event_type: str,
        event_data: dict | None = None,
        actor: str | None = None,
    ) -> str:
        """
        Record a new engagement event.

        Args:
            engagement_id: Engagement ID
            event_type: Type of event (e.g. 'scan_started', 'finding_discovered', 'status_changed')
            event_data: Optional dictionary of event-specific data
            actor: Optional identifier of who triggered the event

        Returns:
            The ID of the created event
        """
        event_id = str(uuid.uuid4())

        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO engagement_events (
                    id, engagement_id, event_type, event_data, actor, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, NOW()
                )
                """,
                (
                    event_id,
                    engagement_id,
                    event_type,
                    Json(event_data or {}),
                    actor,
                ),
            )
            return event_id

    def get_events(
        self,
        engagement_id: str,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Retrieve events for an engagement, optionally filtered by type.

        Args:
            engagement_id: Engagement ID
            event_type: Optional event type filter
            limit: Maximum number of records to return

        Returns:
            List of event dictionaries ordered by most recent first
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            if event_type:
                cursor.execute(
                    """
                    SELECT * FROM engagement_events
                    WHERE engagement_id = %s AND event_type = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (engagement_id, event_type, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM engagement_events
                    WHERE engagement_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (engagement_id, limit),
                )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_event_timeline(self, engagement_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        """
        Retrieve chronological event timeline for an engagement.

        Args:
            engagement_id: Engagement ID
            limit: Maximum number of records
            offset: Number of records to skip

        Returns:
            List of event dictionaries ordered oldest to newest
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                """
                SELECT * FROM engagement_events
                WHERE engagement_id = %s
                ORDER BY created_at ASC
                LIMIT %s OFFSET %s
                """,
                (engagement_id, limit, offset),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
