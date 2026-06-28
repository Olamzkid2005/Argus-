"""EngagementService — DB queries for engagement state and configuration.

Extracted from Orchestrator to reduce orchestrator.py's scope.
All methods are @staticmethod taking ``engagement_id`` as the first parameter.
"""

from __future__ import annotations

import logging

from config.constants import HARD_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class EngagementService:
    """Static service for engagement-level DB queries and state checks.

    Every method is a pure function of ``engagement_id`` with no
    dependency on Orchestrator instance state.
    """

    @staticmethod
    def load_priority_vuln_classes(engagement_id: str) -> list[str]:
        """Load priority_vuln_classes from the engagement record."""
        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT priority_vuln_classes FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                if row and row[0]:
                    return list(row[0])
                return []
        except Exception as e:
            logger.warning(
                "Failed to load priority_vuln_classes for %s: %s",
                engagement_id,
                e,
            )
            return []

    @staticmethod
    def get_scan_state(engagement_id: str) -> str:
        """Return the current status of the engagement."""
        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                return row[0] if row else "recon"
        except (ValueError, OSError, KeyError) as e:
            logger.warning(
                "State check failed for engagement %s: %s — defaulting to 'failed'",
                engagement_id,
                e,
            )
            return "failed"

    @staticmethod
    def load_authorized_scope(engagement_id: str) -> dict | None:
        """Load the authorized scope from the engagement record.

        The scope is stored inside the ``metadata`` JSONB column as
        ``metadata->>'authorized_scope'`` (a JSON string of the form
        ``{"domains": [...], "ipRanges": [...]}``).

        Returns the parsed scope dict or ``None`` if the engagement
        has no explicit scope configured.
        """
        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT metadata->>'authorized_scope' FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                if row and row[0]:
                    import json

                    scope_str = row[0]
                    if isinstance(scope_str, str):
                        return json.loads(scope_str)
                    return dict(scope_str)
                return None
        except Exception as e:
            logger.warning(
                "Failed to load authorized_scope for %s: %s",
                engagement_id,
                e,
            )
            return None

    @staticmethod
    def log_timeout_event(engagement_id: str, elapsed_seconds: float) -> None:
        """Log a hard timeout event for the engagement."""
        logger.warning(
            "Engagement %s exceeded hard timeout. Elapsed: %.2fs, Limit: %ds",
            engagement_id,
            elapsed_seconds,
            HARD_TIMEOUT_SECONDS,
        )
