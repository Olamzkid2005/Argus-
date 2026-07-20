"""Hypothesis repository for database operations on hypotheses."""

import json
import logging
from datetime import datetime

from psycopg2.extras import Json, RealDictCursor

from database.repositories.base import BaseRepository
from tool_core._compat import utc

logger = logging.getLogger(__name__)


class HypothesisRepository(BaseRepository):
    """Repository for hypotheses table CRUD operations.

    Follows the BaseRepository pattern and uses direct SQL for
    create/read/update operations since the hypotheses table has
    JSONB columns that need special handling.
    """

    table_name = "hypotheses"
    id_column = "id"

    def create(self, hypothesis: dict) -> dict | None:
        """Insert a hypothesis using INSERT ... ON CONFLICT DO NOTHING.

        The unique indexes on (engagement_id, root_cause_key) and
        (engagement_id, source_finding_id) prevent duplicate rows from
        concurrent run_analysis() calls.

        Returns the created dict, or None if a conflicting row exists.
        """
        with self.db_operation(commit=True,
                               cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO hypotheses (
                    id, engagement_id, description, root_cause_key,
                    source_finding_id, confidence, status,
                    verification_steps, finding_ids,
                    supporting_finding_ids, refuting_finding_ids,
                    suggested_tools, created_at, updated_at
                ) VALUES (
                    %(id)s, %(engagement_id)s, %(description)s, %(root_cause_key)s,
                    %(source_finding_id)s, %(confidence)s, %(status)s,
                    %(verification_steps)s, %(finding_ids)s,
                    %(supporting_finding_ids)s, %(refuting_finding_ids)s,
                    %(suggested_tools)s, %(created_at)s, %(updated_at)s
                )
                ON CONFLICT (engagement_id, root_cause_key)
                WHERE root_cause_key IS NOT NULL
                DO NOTHING
                RETURNING *
                """,
                {
                    "id": hypothesis.get("id"),
                    "engagement_id": hypothesis.get("engagement_id"),
                    "description": hypothesis.get("description", ""),
                    "root_cause_key": hypothesis.get("root_cause_key"),
                    "source_finding_id": hypothesis.get("source_finding_id"),
                    "confidence": hypothesis.get("confidence", 0.5),
                    "status": hypothesis.get("status", "UNVERIFIED"),
                    "verification_steps": Json(
                        hypothesis.get("verification_steps", [])),
                    "finding_ids": Json(hypothesis.get("finding_ids", [])),
                    "supporting_finding_ids": Json(
                        hypothesis.get("supporting_finding_ids", [])),
                    "refuting_finding_ids": Json(
                        hypothesis.get("refuting_finding_ids", [])),
                    "suggested_tools": Json(
                        hypothesis.get("suggested_tools", [])),
                    "created_at": hypothesis.get("created_at",
                        datetime.now(utc).isoformat()),
                    "updated_at": hypothesis.get("updated_at",
                        datetime.now(utc).isoformat()),
                },
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            # Conflicting row exists — fetch and return it
            cursor.execute(
                """
                SELECT * FROM hypotheses
                WHERE engagement_id = %s AND root_cause_key = %s
                """,
                (hypothesis.get("engagement_id"),
                 hypothesis.get("root_cause_key")),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_by_engagement(
        self,
        engagement_id: str,
        status: str | None = None,
    ) -> list[dict]:
        """Get hypotheses for an engagement, optionally filtered by status.

        Returns hypotheses sorted by confidence descending.
        """
        with self.db_operation(cursor_factory=RealDictCursor) as (conn, cursor):
            if status:
                cursor.execute(
                    """
                    SELECT * FROM hypotheses
                    WHERE engagement_id = %s AND status = %s
                    ORDER BY confidence DESC
                    """,
                    (engagement_id, status),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM hypotheses
                    WHERE engagement_id = %s
                    ORDER BY confidence DESC
                    """,
                    (engagement_id,),
                )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def update(self, hypothesis_id: str, updates: dict) -> dict | None:
        """Update a hypothesis by ID.

        Supports partial updates. Always sets updated_at to NOW().
        Returns the updated dict, or None if the row was not found.

        Raises ValueError if updates contain invalid column names.
        """
        # Build SET clause from updates dict
        allowed_columns = {
            "description", "root_cause_key", "source_finding_id",
            "confidence", "status", "verification_steps", "finding_ids",
            "supporting_finding_ids", "refuting_finding_ids",
            "suggested_tools",
        }
        invalid = [k for k in updates if k not in allowed_columns]
        if invalid:
            raise ValueError(
                f"Invalid columns for hypotheses update: {invalid}")

        if not updates:
            return self.find_by_id(hypothesis_id)

        set_items = []
        values = []
        for key, value in updates.items():
            if key in ("verification_steps", "finding_ids",
                       "supporting_finding_ids", "refuting_finding_ids",
                       "suggested_tools"):
                set_items.append(f"{key} = %s::jsonb")
                values.append(json.dumps(value) if not isinstance(value, str)
                              else value)
            else:
                set_items.append(f"{key} = %s")
                values.append(value)
        set_items.append("updated_at = NOW()")
        values.append(hypothesis_id)

        with self.db_operation(commit=True,
                               cursor_factory=RealDictCursor) as (conn, cursor):
            query = (
                f"UPDATE hypotheses SET "
                f"{', '.join(set_items)} "
                f"WHERE id = %s RETURNING *"
            )
            cursor.execute(query, values)
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_by_engagement(self, engagement_id: str) -> int:
        """Delete all hypotheses for an engagement.

        Returns the number of deleted rows.
        """
        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                "DELETE FROM hypotheses WHERE engagement_id = %s",
                (engagement_id,),
            )
            return cursor.rowcount
