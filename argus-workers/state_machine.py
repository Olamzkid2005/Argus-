"""
Engagement State Machine - Enforces valid state transitions

Uses the shared connection pool from database/connection.py.
Supports passing an external connection for transaction support.
"""
from typing import Dict, List, Optional
import psycopg2
import uuid

from database.connection import get_db


class InvalidStateTransition(Exception):
    """Raised when invalid state transition is attempted"""
    pass


class EngagementStateMachine:
    """
    Enforces valid engagement state transitions and records history
    """

    # Valid engagement states
    STATES = [
        "created",
        "recon",
        "awaiting_approval",
        "scanning",
        "analyzing",
        "reporting",
        "complete",
        "failed",
        "paused",
    ]

    # Valid state transitions
    TRANSITIONS = {
        "created": ["recon", "failed"],
        "recon": ["awaiting_approval", "failed", "paused"],
        "awaiting_approval": ["scanning", "paused", "failed"],
        "scanning": ["analyzing", "failed", "paused"],
        "analyzing": ["reporting", "recon", "failed"],  # Can loop back to recon
        "reporting": ["complete", "failed"],
        "paused": ["recon", "scanning", "analyzing"],
        "failed": [],
        "complete": [],
    }

    def __init__(self, engagement_id: str, db_connection_string: Optional[str] = None,
                 current_state: str = "created", connection: Optional[psycopg2.extensions.connection] = None):
        """
        Initialize State Machine

        Args:
            engagement_id: Engagement ID
            db_connection_string: PostgreSQL connection string (deprecated, use connection instead)
            current_state: Current engagement state
            connection: External connection for transaction support
        """
        self.engagement_id = engagement_id
        self._db_conn_string = db_connection_string
        self._external_conn = connection
        self.current_state = current_state

        if current_state not in self.STATES:
            raise ValueError(f"Invalid state: {current_state}")

    def _get_connection(self):
        """Get a database connection (external or from pool)"""
        if self._external_conn:
            return self._external_conn
        if self._db_conn_string:
            return psycopg2.connect(self._db_conn_string)
        return get_db().get_connection()

    def _release_connection(self, conn):
        """Release connection back to pool (skip if external)"""
        if conn and not self._external_conn and not self._db_conn_string:
            get_db().release_connection(conn)

    def transition(self, new_state: str, reason: Optional[str] = None):
        """
        Enforce valid state transitions

        Args:
            new_state: Target state
            reason: Reason for transition

        Raises:
            InvalidStateTransition: If transition is invalid
        """
        # Validate new state
        if new_state not in self.STATES:
            raise ValueError(f"Invalid state: {new_state}")

        # Check if transition is valid
        if not self.can_transition_to(new_state):
            raise InvalidStateTransition(
                f"Invalid transition from {self.current_state} to {new_state}. "
                f"Valid transitions: {self.TRANSITIONS[self.current_state]}"
            )

        old_state = self.current_state

        # Handle loop-back transitions - use atomic state+budget update
        if old_state == "analyzing" and new_state == "recon":
            self._persist_state_and_budget(
                from_state=old_state,
                to_state=new_state,
                reason=reason or f"Transition to {new_state}"
            )
        else:
            self._persist_state_and_budget(
                from_state=old_state,
                to_state=new_state,
                reason=reason or f"Transition to {new_state}"
            )

        # Update current state
        self.current_state = new_state

    def _persist_state_and_budget(self, from_state: str, to_state: str, reason: str):
        """
        Atomically record state transition and update loop budget if needed.
        Uses a single transaction for consistency.

        Args:
            from_state: Source state
            to_state: Target state
            reason: Reason for transition
        """
        conn = self._get_connection()
        should_release = False

        try:
            cursor = conn.cursor()

            # Record state transition
            transition_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO engagement_states (
                    id, engagement_id, from_state, to_state, reason, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, NOW()
                )
                """,
                (transition_id, self.engagement_id, from_state, to_state, reason)
            )

            # Update engagement status
            cursor.execute(
                """
                UPDATE engagements
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (to_state, self.engagement_id)
            )

            # If looping back from analyzing to recon, increment budget
            if from_state == "analyzing" and to_state == "recon":
                cursor.execute(
                    """
                    UPDATE loop_budgets
                    SET current_cycles = current_cycles + 1, updated_at = NOW()
                    WHERE engagement_id = %s
                    """,
                    (self.engagement_id,)
                )

            conn.commit()
            cursor.close()

        except Exception as e:
            conn.rollback()
            print(f"Failed to persist state transition: {e}")
            raise
        finally:
            if not self._external_conn:
                self._release_connection(conn)

    def _record_transition(self, from_state: str, to_state: str, reason: str):
        """
        Record state transition in database (legacy, use _persist_state_and_budget instead)

        Args:
            from_state: Source state
            to_state: Target state
            reason: Reason for transition
        """
        conn = self._get_connection()
        should_release = False

        try:
            cursor = conn.cursor()

            transition_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO engagement_states (
                    id, engagement_id, from_state, to_state, reason, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, NOW()
                )
                """,
                (transition_id, self.engagement_id, from_state, to_state, reason)
            )

            # Update engagement status
            cursor.execute(
                """
                UPDATE engagements
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (to_state, self.engagement_id)
            )

            conn.commit()
            cursor.close()

        except Exception as e:
            conn.rollback()
            print(f"Failed to record transition: {e}")
            raise
        finally:
            if not self._external_conn:
                self._release_connection(conn)

    def _increment_loop_budget_cycle(self):
        """
        Increment loop budget cycle counter on loop-back transition
        """
        conn = self._get_connection()

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE loop_budgets
                SET current_cycles = current_cycles + 1
                WHERE engagement_id = %s
                """,
                (self.engagement_id,)
            )
            conn.commit()
            cursor.close()

        except Exception as e:
            conn.rollback()
            print(f"Failed to increment loop budget cycle: {e}")
        finally:
            if not self._external_conn:
                self._release_connection(conn)

    def get_transition_history(self) -> List[Dict]:
        """
        Get transition history for engagement

        Returns:
            List of transition records
        """
        conn = self._get_connection()

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT from_state, to_state, reason, created_at
                FROM engagement_states
                WHERE engagement_id = %s
                ORDER BY created_at ASC
                """,
                (self.engagement_id,)
            )

            rows = cursor.fetchall()
            cursor.close()

            history = []
            for row in rows:
                history.append({
                    "from_state": row[0],
                    "to_state": row[1],
                    "reason": row[2],
                    "timestamp": row[3].isoformat() if row[3] else None,
                })

            return history

        finally:
            if not self._external_conn:
                self._release_connection(conn)

    def get_valid_transitions(self) -> List[str]:
        """
        Get valid transitions from current state

        Returns:
            List of valid target states
        """
        return self.TRANSITIONS.get(self.current_state, [])

    def can_transition_to(self, new_state: str) -> bool:
        """
        Check if transition to new_state is valid from current state

        Args:
            new_state: Target state to transition to

        Returns:
            True if transition is valid, False otherwise
        """
        return new_state in self.TRANSITIONS.get(self.current_state, [])
