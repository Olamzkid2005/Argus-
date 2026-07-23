"""
database/sqlite_checkpoint.py — SQLite-backed checkpoint manager for local mode.

Provides checkpoint save/load/resume for the CLI's ``argus assess --local``
flow, enabling recovery from crashes mid-assessment. Each phase completion
saves a checkpoint with engagement metadata, and a ``resume`` command can
pick up where the last assessment left off.

Usage::

    from database.sqlite_checkpoint import SQLiteCheckpointManager

    mgr = SQLiteCheckpointManager(":memory:")
    cpid = mgr.save_checkpoint(engagement_id, "scan", {
        "target": "https://example.com",
        "phase_results": [...],
    })
    plan = mgr.get_resume_plan(engagement_id)
    mgr.close()
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResumePlan:
    """Resume plan derived from the latest checkpoint."""

    engagement_id: str
    completed_phase: str | None
    next_phase: str | None
    remaining_phases: list[str]
    partial_results: dict
    checkpoint_timestamp: str
    can_resume: bool
    reason: str = ""


_PHASE_ORDER = ["recon", "scan", "analyze", "report"]


def _now_iso() -> str:
    """Return ISO 8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create checkpoints table if it doesn't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_checkpoints_engagement
            ON checkpoints(engagement_id, created_at DESC);
    """)


class SQLiteCheckpointManager:
    """SQLite-backed checkpoint manager for standalone/local mode.

    Thread-safe via per-operation lock. Uses the same SQLite connection
    pattern as ``SQLiteEngagementRepo``.
    """

    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._closed = False
        with self._lock:
            _ensure_tables(self._conn)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    # ── Public API ───────────────────────────────────────────────────

    def save_checkpoint(self, engagement_id: str, phase: str, data: dict) -> str:
        """Save a checkpoint for a completed phase.

        Args:
            engagement_id: Engagement UUID.
            phase: Phase name (e.g. ``recon``, ``scan``).
            data: Arbitrary JSON-serializable data to checkpoint.

        Returns:
            Checkpoint ID.
        """
        cp_id = str(uuid.uuid4())
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """INSERT INTO checkpoints (id, engagement_id, phase, data, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (cp_id, engagement_id, phase, json.dumps(data, default=str), now),
            )
            self._conn.commit()
            logger.debug("Saved checkpoint %s for %s/%s", cp_id[:8], engagement_id[:8], phase)
        return cp_id

    def load_latest_checkpoint(self, engagement_id: str) -> dict | None:
        """Load the most recent checkpoint for an engagement.

        Args:
            engagement_id: Engagement UUID.

        Returns:
            Checkpoint dict with keys: ``id``, ``engagement_id``, ``phase``,
            ``data`` (parsed JSON), ``created_at``. Returns None if no
            checkpoint exists.
        """
        with self._lock:
            cursor = self._conn.execute(
                """SELECT id, engagement_id, phase, data, created_at
                   FROM checkpoints
                   WHERE engagement_id = ?
                   ORDER BY created_at DESC
                   LIMIT 1""",
                (engagement_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "engagement_id": row[1],
                "phase": row[2],
                "data": json.loads(row[3]) if isinstance(row[3], str) else row[3],
                "created_at": row[4],
            }

    def get_resume_plan(self, engagement_id: str) -> ResumePlan | None:
        """Determine what to resume from the latest checkpoint.

        Args:
            engagement_id: Engagement UUID.

        Returns:
            ResumePlan describing the next phase to run, or None if
            no checkpoint exists or the engagement is already complete.
        """
        cp = self.load_latest_checkpoint(engagement_id)
        if cp is None:
            return None

        phase = cp["phase"]
        data = cp.get("data", {})

        # If the last completed phase is 'report', nothing to resume
        if phase == "report":
            return ResumePlan(
                engagement_id=engagement_id,
                completed_phase="report",
                next_phase=None,
                remaining_phases=[],
                partial_results=data,
                checkpoint_timestamp=cp["created_at"],
                can_resume=False,
                reason="Assessment already completed report phase",
            )

        # Find the next phase after the last completed one
        if phase in _PHASE_ORDER:
            idx = _PHASE_ORDER.index(phase)
            remaining = _PHASE_ORDER[idx + 1:]
            next_phase = remaining[0] if remaining else None
            return ResumePlan(
                engagement_id=engagement_id,
                completed_phase=phase,
                next_phase=next_phase,
                remaining_phases=remaining,
                partial_results=data,
                checkpoint_timestamp=cp["created_at"],
                can_resume=next_phase is not None,
                reason=f"Resuming after completed '{phase}' phase",
            )

        return ResumePlan(
            engagement_id=engagement_id,
            completed_phase=None,
            next_phase="recon",
            remaining_phases=_PHASE_ORDER,
            partial_results=data,
            checkpoint_timestamp=cp["created_at"],
            can_resume=True,
            reason=f"Unknown phase '{phase}' — restarting from beginning",
        )

    def has_checkpoint(self, engagement_id: str) -> bool:
        """Check if any checkpoints exist for an engagement."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT 1 FROM checkpoints WHERE engagement_id = ? LIMIT 1",
                (engagement_id,),
            )
            return cursor.fetchone() is not None

    def delete_checkpoints(self, engagement_id: str) -> int:
        """Delete all checkpoints for an engagement.

        Args:
            engagement_id: Engagement UUID.

        Returns:
            Number of checkpoints deleted.
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM checkpoints WHERE engagement_id = ?",
                (engagement_id,),
            )
            self._conn.commit()
            count = cursor.rowcount
            if count:
                logger.info("Deleted %d checkpoint(s) for %s", count, engagement_id[:8])
            return count

    def list_checkpoints(self, engagement_id: str) -> list[dict]:
        """List all checkpoint metadata for an engagement (data excluded)."""
        with self._lock:
            cursor = self._conn.execute(
                """SELECT id, engagement_id, phase, created_at
                   FROM checkpoints
                   WHERE engagement_id = ?
                   ORDER BY created_at DESC""",
                (engagement_id,),
            )
            return [
                {
                    "id": row[0],
                    "engagement_id": row[1],
                    "phase": row[2],
                    "created_at": row[3],
                }
                for row in cursor.fetchall()
            ]
