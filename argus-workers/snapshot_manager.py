"""
Snapshot Manager - Creates immutable state snapshots for decision-making
"""

import logging
import uuid
from datetime import datetime
from tool_core._compat import utc
from decimal import Decimal

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from database.connection import get_db

logger = logging.getLogger(__name__)


class SnapshotManager:
    """
    Creates and manages immutable state snapshots for Intelligence Engine
    """

    def __init__(self, db_connection_string: str = ""):
        """
        Initialize Snapshot Manager

        Args:
            db_connection_string: Deprecated — connection pooling is used instead.
        """
        self.db_conn_string = db_connection_string
        if db_connection_string:
            logger.warning(
                "db_connection_string is deprecated for SnapshotManager — "
                "connection pooling is preferred. Remove this parameter."
            )

    def _get_connection(self):
        """Get a database connection from the pool (C5 fix)."""
        return get_db().get_connection()

    def _release_connection(self, conn):
        """Release connection back to pool (C5 fix).
        Resets isolation level before returning to avoid side effects."""
        if conn is None:
            return
        try:
            # Reset isolation level to default before returning to pool
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_READ_COMMITTED)
        except Exception:
            logger.warning(
                "Failed to reset isolation level on connection before returning to pool",
                exc_info=True,
            )
        try:
            get_db().release_connection(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                logger.warning(
                    "Failed to close connection after failed release_connection",
                    exc_info=True,
                )

    def create_snapshot(self, engagement_id: str) -> dict:
        """
        Create immutable snapshot of engagement state

        Uses SERIALIZABLE isolation level to ensure consistency.
        Captures: findings, attack graph, loop budget, engagement state

        Args:
            engagement_id: Engagement ID

        Returns:
            Snapshot dictionary with all state data
        """
        conn = None
        cursor = None
        max_retries = 3
        retry_delay = 1  # seconds, doubles each attempt
        import time

        for attempt in range(max_retries):
            last_error = None
            try:
                conn = self._get_connection()
                # Set SERIALIZABLE isolation level
                conn.set_isolation_level(
                    psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE
                )

                cursor = conn.cursor(cursor_factory=RealDictCursor)

                # Capture findings
                cursor.execute(
                    """
                    SELECT
                        id, type, severity, confidence, endpoint,
                        evidence, source_tool, cvss_score, evidence_strength,
                        tool_agreement_level, fp_likelihood, created_at
                    FROM findings
                    WHERE engagement_id = %s
                    ORDER BY created_at DESC
                    """,
                    (engagement_id,),
                )
                findings = [dict(row) for row in cursor.fetchall()]

                # Capture attack graph (attack_paths) including chain exploit scripts
                cursor.execute(
                    """
                    SELECT
                        id, path_nodes, risk_score, normalized_severity,
                        chain_exploit_script, created_at
                    FROM attack_paths
                    WHERE engagement_id = %s
                    ORDER BY risk_score DESC
                    """,
                    (engagement_id,),
                )
                attack_paths = [dict(row) for row in cursor.fetchall()]

                # Capture loop budget
                cursor.execute(
                    """
                    SELECT
                        max_cycles, max_depth,
                        current_cycles, current_depth
                    FROM loop_budgets
                    WHERE engagement_id = %s
                    """,
                    (engagement_id,),
                )
                loop_budget_row = cursor.fetchone()
                loop_budget = dict(loop_budget_row) if loop_budget_row else {}

                # Capture engagement state
                cursor.execute(
                    """
                    SELECT status, target_url, authorized_scope, rate_limit_config
                    FROM engagements
                    WHERE id = %s
                    """,
                    (engagement_id,),
                )
                engagement_row = cursor.fetchone()
                engagement_state = dict(engagement_row) if engagement_row else {}

                # Create snapshot data
                snapshot_data = {
                    "engagement_id": engagement_id,
                    "findings": findings,
                    "attack_graph": {
                        "paths": attack_paths,
                    },
                    "loop_budget": loop_budget,
                    "engagement_state": engagement_state,
                    "snapshot_timestamp": datetime.now(utc).isoformat(),
                }

                # Convert DB-native types (e.g. Decimal) into JSON-safe values
                snapshot_data = self._to_jsonable(snapshot_data)

                # Store snapshot in database
                snapshot_id = self._store_snapshot(engagement_id, snapshot_data, cursor)

                conn.commit()

                # Add snapshot ID to data
                snapshot_data["snapshot_id"] = snapshot_id

                return snapshot_data

            except Exception as e:
                if conn:
                    conn.rollback()
                # Check for serialization or unique-violation failures
                if conn:
                    try:
                        from psycopg2.errorcodes import (
                            SERIALIZATION_FAILURE,
                            UNIQUE_VIOLATION,
                        )

                        pgcode = getattr(e, "pgcode", None)
                        if (
                            pgcode in (SERIALIZATION_FAILURE, UNIQUE_VIOLATION)
                            and attempt < max_retries - 1
                        ):
                            logger.info(
                                "Snapshot version conflict (%s) "
                                "(attempt %d/%d), retrying in %ds",
                                "serialization" if pgcode == SERIALIZATION_FAILURE else "unique_violation",
                                attempt + 1,
                                max_retries,
                                retry_delay * (2**attempt),
                            )
                            time.sleep(retry_delay * (2**attempt))
                            continue
                    except Exception:
                        logger.debug(
                            "Failed to inspect pgcode for snapshot retry", exc_info=True
                        )
                # Re-raise all non-retryable exceptions immediately
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"Failed to create snapshot after {max_retries} attempts: {e}"
                    ) from e
                else:
                    raise  # Non-retryable failures: don't retry silently
            finally:
                if cursor:
                    cursor.close()
                    cursor = None
                if conn:
                    self._release_connection(conn)
                    conn = None

        # Fallback: should never reach here (loop always raises or returns)
        return {}

    def _to_jsonable(self, value):
        """Recursively convert values to JSON-safe types."""
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: self._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._to_jsonable(v) for v in value]
        return value

    def _store_snapshot(self, engagement_id: str, snapshot_data: dict, cursor) -> str:
        """
        Store snapshot in decision_snapshots table

        Computes the version via SELECT MAX(version)+1 within the active
        SERIALIZABLE transaction. Concurrent workers are handled by the
        outer retry loop in create_snapshot(), which retries on both
        SERIALIZATION_FAILURE and UNIQUE_VIOLATION. This avoids depending
        on an ON CONFLICT clause (which requires a unique constraint that
        may or may not exist on the table).

        Args:
            engagement_id: Engagement ID
            snapshot_data: Snapshot data dictionary
            cursor: Database cursor

        Returns:
            Snapshot ID
        """
        snapshot_id = str(uuid.uuid4())

        # Get next version number — the SERIALIZABLE isolation level and
        # outer retry loop handle concurrent-writer races.
        cursor.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 as next_version
            FROM decision_snapshots
            WHERE engagement_id = %s
            """,
            (engagement_id,),
        )
        version = cursor.fetchone()["next_version"]

        cursor.execute(
            """
            INSERT INTO decision_snapshots (
                id, engagement_id, version, snapshot_data, created_at
            ) VALUES (
                %s, %s, %s, %s, NOW()
            )
            """,
            (snapshot_id, engagement_id, version, Json(snapshot_data)),
        )

        return snapshot_id

    def _execute_query(
        self, query: str, params: tuple, fetch: str = "all"
    ) -> list[dict] | dict | None:
        """Execute a read-only query using pool connections (C5 fix)."""
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            if fetch == "one":
                row = cursor.fetchone()
                return dict(row) if row else None
            else:
                return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            if conn:
                self._release_connection(conn)

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        """
        Retrieve snapshot by ID

        Args:
            snapshot_id: Snapshot ID

        Returns:
            Snapshot data or None if not found
        """
        result = self._execute_query(
            """
            SELECT id, engagement_id, version, snapshot_data, created_at
            FROM decision_snapshots
            WHERE id = %s
            """,
            (snapshot_id,),
            fetch="one",
        )
        if isinstance(result, dict):
            return result
        return None

    def get_latest_snapshot(self, engagement_id: str) -> dict | None:
        """
        Get latest snapshot for engagement

        Args:
            engagement_id: Engagement ID

        Returns:
            Latest snapshot data or None
        """
        result = self._execute_query(
            """
            SELECT id, engagement_id, version, snapshot_data, created_at
            FROM decision_snapshots
            WHERE engagement_id = %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (engagement_id,),
            fetch="one",
        )
        if isinstance(result, dict):
            return result
        return None

    def list_snapshots(self, engagement_id: str) -> list[dict]:
        """
        List all snapshots for engagement

        Args:
            engagement_id: Engagement ID

        Returns:
            List of snapshot metadata (without full data)
        """
        result = self._execute_query(
            """
            SELECT id, engagement_id, version, created_at
            FROM decision_snapshots
            WHERE engagement_id = %s
            ORDER BY version DESC
            LIMIT 100
            """,
            (engagement_id,),
            fetch="all",
        )
        if isinstance(result, list):
            return result
        return []
