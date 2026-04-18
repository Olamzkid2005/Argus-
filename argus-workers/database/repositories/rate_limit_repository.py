"""
Repository for rate limit events.
"""

from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class RateLimitRepository:
    """Repository for managing rate limit events."""
    
    def __init__(self, db_connection):
        """
        Initialize repository.
        
        Args:
            db_connection: Database connection
        """
        self.db = db_connection
    
    async def create_event(
        self,
        domain: str,
        event_type: str,
        status_code: Optional[int],
        current_rps: float
    ) -> dict:
        """
        Create rate limit event record.
        
        Args:
            domain: Target domain
            event_type: Type of rate limit event
            status_code: HTTP status code if applicable
            current_rps: Current requests per second
        
        Returns:
            Created event record
        """
        query = """
            INSERT INTO rate_limit_events (
                domain,
                event_type,
                status_code,
                current_rps,
                created_at
            )
            VALUES ($1, $2, $3, $4, NOW())
            RETURNING id, domain, event_type, status_code, current_rps, created_at
        """
        
        try:
            result = await self.db.fetchrow(
                query,
                domain,
                event_type,
                status_code,
                current_rps
            )
            
            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to create rate limit event: {e}")
            raise
    
    async def get_recent_events(
        self,
        domain: str,
        limit: int = 100
    ) -> list:
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
            WHERE domain = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        
        try:
            results = await self.db.fetch(query, domain, limit)
            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Failed to get rate limit events: {e}")
            raise
