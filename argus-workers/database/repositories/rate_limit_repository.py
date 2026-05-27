"""
Repository for rate limit events.

Uses standard cursor pattern (not asyncpg-style) to avoid runtime crashes (H-25).
"""

import logging

from database.connection import db_cursor

logger = logging.getLogger(__name__)


class RateLimitRepository:
    """Repository for managing rate limit events."""

    def __init__(self, db_connection=None):
        """
        Initialize repository.

        Args:
            db_connection: Database connection (optional, uses db_cursor if None)
        """
        self.db = db_connection

    def create_event(
        self,
        domain: str,
        event_type: str,
        status_code: int | None,
        current_rps: float
    ) -> dict | None:
        """
        Create rate limit event record.

        Args:
            domain: Target domain
            event_type: Type of rate limit event
            status_code: HTTP status code if applicable
            current_rps: Current requests per second

        Returns:
            Created event record or None
        """
        query = """
            INSERT INTO rate_limit_events (
                domain,
                event_type,
                status_code,
                current_rps,
                created_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id, domain, event_type, status_code, current_rps, created_at
        """

        try:
            if self.db:
                with self.db.cursor() as cursor:
                    cursor.execute(query, (domain, event_type, status_code, current_rps))
                    row = cursor.fetchone()
                    return dict(row) if row else None
            else:
                with db_cursor() as cursor:
                    cursor.execute(query, (domain, event_type, status_code, current_rps))
                    row = cursor.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            logger.error("Failed to create rate limit event: %s", e)
            raise

    def get_recent_events(
        self,
        domain: str,
        limit: int = 100
    ) -> list[dict]:
        """
        Get recent rate limit events for domain.

        Args:
            domain: Target domain
            limit: Maximum number of events to return

        Returns:
            List of rate limit events
        """
        query = """
            SELECT id, domain, event_type, status_code, current_rps, created_at
            FROM rate_limit_events
            WHERE domain = %s
            ORDER BY created_at DESC
            LIMIT %s
        """

        try:
            if self.db:
                with self.db.cursor() as cursor:
                    cursor.execute(query, (domain, limit))
                    return [dict(row) for row in cursor.fetchall()]
            else:
                with db_cursor() as cursor:
                    cursor.execute(query, (domain, limit))
                    return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("Failed to get rate limit events: %s", e)
            raise
