"""
Engagement events repository for event sourcing operations
"""
from typing import Dict, List, Optional
import uuid
from psycopg2.extras import RealDictCursor, Json
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
        event_data: Optional[dict] = None,
        actor: Optional[str] = None,
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
        conn = self._get_connection()
        cursor = conn.cursor()

        event_id = str(uuid.uuid4())

        try:
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
            if not self._external_conn:
                conn.commit()
            return event_id
        except Exception as e:
            if not self._external_conn:
                conn.rollback()
            raise e
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def get_events(
        self,
        engagement_id: str,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Retrieve events for an engagement, optionally filtered by type.

        Args:
            engagement_id: Engagement ID
            event_type: Optional event type filter
            limit: Maximum number of records to return

        Returns:
            List of event dictionaries ordered by most recent first
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
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
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def get_event_timeline(self, engagement_id: str) -> List[Dict]:
        """
        Retrieve chronological event timeline for an engagement.

        Args:
            engagement_id: Engagement ID

        Returns:
            List of event dictionaries ordered oldest to newest
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT * FROM engagement_events
                WHERE engagement_id = %s
                ORDER BY created_at ASC
                """,
                (engagement_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)
