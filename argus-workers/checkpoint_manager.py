"""
Checkpoint Manager - Saves and recovers from checkpoints during long scans
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from database.connection import DatabaseConnectionError, get_db
from tool_core._compat import utc

logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    Manages checkpoints for engagement recovery after worker crashes
    """

    def __init__(self, db_connection_string: str = ""):
        self.db_conn_string = db_connection_string

    @staticmethod
    def _ensure_db() -> None:
        """Verify the database connection pool is initialized (M5).
        Raises RuntimeError if get_db() is not ready."""
        try:
            db = get_db()
            if db is None:
                raise RuntimeError(
                    "Database pool is not initialized (get_db() returned None)"
                )
            # Quick connectivity check
            conn = db.get_connection()
            db.release_connection(conn)
        except (DatabaseConnectionError, RuntimeError, Exception) as e:
            raise RuntimeError(
                f"Cannot access database for checkpoint operations: {e}"
            ) from e

    def save_checkpoint(self, engagement_id: str, phase: str, data: dict) -> str:
        """
        Save checkpoint after completing a phase

        Args:
            engagement_id: Engagement ID
            phase: Phase name (recon, scan, analyze)
            data: Partial results data

        Returns:
            Checkpoint ID
        """
        self._ensure_db()  # M5: verify DB is initialized before proceeding
        conn = None
        cursor = None

        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            checkpoint_id = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO checkpoints (
                    id, engagement_id, phase, data, created_at
                ) VALUES (
                    %s, %s, %s, %s, NOW()
                )
                """,
                (checkpoint_id, engagement_id, phase, Json(data)),
            )

            conn.commit()

            return checkpoint_id

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(
                "Failed to save checkpoint for %s/%s: %s", engagement_id, phase, e
            )
            raise RuntimeError(
                f"Failed to save checkpoint for {engagement_id}/{phase}: {e}"
            ) from e
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def load_checkpoint(self, engagement_id: str) -> dict | None:
        """
        Load last checkpoint for engagement

        Args:
            engagement_id: Engagement ID

        Returns:
            Checkpoint data or None if no checkpoint exists
        """
        conn = None
        cursor = None

        try:
            conn = get_db().get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT id, engagement_id, phase, data, created_at
                FROM checkpoints
                WHERE engagement_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (engagement_id,),
            )

            row = cursor.fetchone()

            if row:
                return dict(row)

            return None

        except Exception as e:
            logger.error("Failed to load checkpoint for %s: %s", engagement_id, e)
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def has_checkpoint(self, engagement_id: str) -> bool:
        """
        Check if checkpoint exists for engagement

        Args:
            engagement_id: Engagement ID

        Returns:
            True if checkpoint exists
        """
        conn = None
        cursor = None

        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM checkpoints
                WHERE engagement_id = %s
                LIMIT 1
                """,
                (engagement_id,),
            )

            return cursor.fetchone() is not None

        except Exception as e:
            logger.error(
                "Failed to check checkpoint existence for %s: %s", engagement_id, e
            )
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def list_checkpoints(self, engagement_id: str) -> list[dict]:
        """
        List all checkpoints for engagement

        Args:
            engagement_id: Engagement ID

        Returns:
            List of checkpoint metadata
        """
        conn = None
        cursor = None

        try:
            conn = get_db().get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT id, engagement_id, phase, created_at
                FROM checkpoints
                WHERE engagement_id = %s
                ORDER BY created_at DESC
                """,
                (engagement_id,),
            )

            return [dict(row) for row in cursor.fetchall()]

        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def delete_checkpoints(self, engagement_id: str):
        """
        Delete all checkpoints for engagement

        Args:
            engagement_id: Engagement ID
        """
        conn = None
        cursor = None

        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM checkpoints
                WHERE engagement_id = %s
                """,
                (engagement_id,),
            )

            conn.commit()

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error("Failed to delete checkpoints for %s: %s", engagement_id, e)
            raise RuntimeError(
                f"Failed to delete checkpoints for {engagement_id}: {e}"
            ) from e
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def _get_engagement_current_phase(self, engagement_id: str) -> str | None:
        """Get the current phase/state of an engagement from the DB.

        Returns None if not found.
        """
        conn = None
        cursor = None
        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM engagements WHERE id = %s",
                (engagement_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            logger.debug(
                "Could not read engagement status for %s", engagement_id, exc_info=True
            )
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def resume_from_checkpoint(self, engagement_id: str) -> dict | None:
        """
        Resume execution from last checkpoint

        Args:
            engagement_id: Engagement ID

        Returns:
            Resume data with phase and partial results, or None
        """
        checkpoint = self.load_checkpoint(engagement_id)

        if not checkpoint:
            return None

        # Don't resume from terminal phases
        if checkpoint["phase"] in ("complete", "failed"):
            logger.info(
                "Checkpoint for %s is in terminal phase '%s' — skipping resume",
                engagement_id,
                checkpoint["phase"],
            )
            return None

        # P3: Verify that the checkpoint phase matches the current engagement
        # phase to avoid resuming from stale/superseded checkpoint data.
        current_phase = self._get_engagement_current_phase(engagement_id)
        if (
            current_phase
            and checkpoint.get("phase") == "scan"
            and current_phase == "recon"
        ):
            logger.info(
                "Checkpoint for %s is from phase '%s' but engagement is now '%s' — "
                "engagement was reset after checkpoint was created, skipping resume",
                engagement_id,
                checkpoint["phase"],
                current_phase,
            )
            return None

        return {
            "engagement_id": engagement_id,
            "resume_phase": checkpoint["phase"],
            "partial_results": checkpoint["data"],
            "checkpoint_timestamp": checkpoint["created_at"].isoformat()
            if checkpoint["created_at"]
            else None,
        }

    def get_resume_plan(self, engagement_id: str) -> dict | None:
        """
        Get a detailed resume plan from the last checkpoint.

        Analyzes the checkpoint data and returns a plan for resuming
        the scan from where it left off.

        Args:
            engagement_id: Engagement ID

        Returns:
            Resume plan with next steps, or None
        """
        checkpoint = self.load_checkpoint(engagement_id)

        if not checkpoint:
            return None

        phase = checkpoint["phase"]
        data = checkpoint["data"]

        # Define phase ordering
        phases = ["recon", "scan", "analyze", "report"]

        if phase in phases:
            current_idx = phases.index(phase)
            next_phase = (
                phases[current_idx + 1] if current_idx + 1 < len(phases) else None
            )
            remaining = phases[current_idx + 1 :] if next_phase else []
        else:
            # Unknown phase — reset to beginning
            return {
                "engagement_id": engagement_id,
                "completed_phase": None,
                "next_phase": "scan",
                "partial_results": data,
                "remaining_phases": ["scan", "analyze", "report"],
                "checkpoint_timestamp": checkpoint["created_at"].isoformat()
                if checkpoint["created_at"]
                else None,
                "can_resume": True,
                "reason": f"Phase '{phase}' not recognized, starting from beginning",
            }

        return {
            "engagement_id": engagement_id,
            "completed_phase": phase,
            "next_phase": next_phase,
            "partial_results": data,
            "remaining_phases": remaining,
            "checkpoint_timestamp": checkpoint["created_at"].isoformat()
            if checkpoint["created_at"]
            else None,
            "can_resume": next_phase is not None,
        }

    def save_tool_checkpoint(self, engagement_id: str, phase: str, tool_name: str, data: dict) -> str:
        """Save a checkpoint for an individual tool execution within a phase.

        Phase 4.1.1: Allows mid-phase checkpointing so that on resume,
        the assessment can skip tools that already completed rather than
        restarting the entire phase. Each tool execution within a phase
        saves a separate checkpoint identified by phase + tool_name.

        Args:
            engagement_id: Engagement ID
            phase: Phase name (e.g., "recon", "scan")
            tool_name: Name of the tool that just executed
            data: Partial results / output from the tool

        Returns:
            Checkpoint ID
        """
        self._ensure_db()
        conn = None
        cursor = None
        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            checkpoint_id = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO checkpoints (
                    id, engagement_id, phase, data, created_at
                ) VALUES (
                    %s, %s, %s, %s, NOW()
                )
                """,
                (checkpoint_id, engagement_id, f"{phase}:{tool_name}", Json(data)),
            )

            conn.commit()
            logger.info(
                "Saved tool checkpoint for %s/%s/%s: %s",
                engagement_id, phase, tool_name, checkpoint_id,
            )
            return checkpoint_id

        except Exception as e:
            if conn:
                conn.rollback()
            logger.warning(
                "Failed to save tool checkpoint for %s/%s/%s: %s",
                engagement_id, phase, tool_name, e,
            )
            return ""
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def get_completed_tools(self, engagement_id: str, phase: str) -> list[str]:
        """Get list of tool names that have been checkpointed for a phase.

        Phase 4.1.3: Used by the workflow runner on resume to skip tools
        that were already completed in a previous run.

        Args:
            engagement_id: Engagement ID
            phase: Phase name

        Returns:
            List of tool names that have checkpoints for this phase
        """
        conn = None
        cursor = None
        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT phase FROM checkpoints
                WHERE engagement_id = %s
                  AND phase LIKE %s
                ORDER BY created_at ASC
                """,
                (engagement_id, f"{phase}:%"),
            )
            rows = cursor.fetchall()
            # Extract tool name from "phase:tool_name" format
            completed = []
            prefix = f"{phase}:"
            for row in rows:
                full_phase = row[0]
                if full_phase.startswith(prefix):
                    tool_name = full_phase[len(prefix):]
                    if tool_name and tool_name not in completed:
                        completed.append(tool_name)
            return completed

        except Exception as e:
            logger.debug(
                "Failed to list completed tools for %s/%s: %s",
                engagement_id, phase, e,
            )
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)

    def cleanup_old_checkpoints(self, max_age_days: int = 7) -> int:
        """
        Delete checkpoints older than specified age.

        Args:
            max_age_days: Maximum age in days

        Returns:
            Number of checkpoints deleted
        """
        conn = None
        cursor = None

        try:
            conn = get_db().get_connection()
            cursor = conn.cursor()
            cutoff = datetime.now(utc) - timedelta(days=max_age_days)

            cursor.execute(
                """
                DELETE FROM checkpoints
                WHERE created_at < %s
                """,
                (cutoff,),
            )

            conn.commit()
            return cursor.rowcount

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error("Failed to cleanup checkpoints: %s", e)
            raise RuntimeError(f"Failed to cleanup checkpoints: {e}") from e
        finally:
            if cursor:
                cursor.close()
            if conn:
                get_db().release_connection(conn)


class CheckpointContext:
    """
    Context manager for automatic checkpoint saving
    """

    def __init__(
        self, checkpoint_manager: CheckpointManager, engagement_id: str, phase: str
    ):
        """
        Initialize checkpoint context

        Args:
            checkpoint_manager: CheckpointManager instance
            engagement_id: Engagement ID
            phase: Phase name
        """
        self.checkpoint_manager = checkpoint_manager
        self.engagement_id = engagement_id
        self.phase = phase
        self.results: dict[str, Any] = {}

    def __enter__(self):
        """Enter context"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Save checkpoint on exit if no exception and results are non-empty"""
        if exc_type is None and self.results:
            # No exception and there are actual results — save checkpoint
            self.checkpoint_manager.save_checkpoint(
                self.engagement_id, self.phase, self.results
            )

    def add_result(self, key: str, value):
        """
        Add result to checkpoint data

        Args:
            key: Result key
            value: Result value
        """
        self.results[key] = value
