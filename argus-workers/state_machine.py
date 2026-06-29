"""
Engagement State Machine - Enforces valid state transitions

Uses the shared connection pool from database/connection.py.
Supports passing an external connection for transaction support.
"""

import logging
import uuid

import psycopg2

from database.connection import DatabaseConnectionError, get_db
from utils.validation import validate_uuid
from exceptions import InvalidStateTransitionError

logger = logging.getLogger(__name__)


def resolve_state_for_phase(phase_name: str) -> str:
    """Translate an agent phase name to the canonical state machine state.

    Returns the state machine state name for the given agent phase.
    If the phase name is already a valid state, returns it as-is.
    If unknown, returns the phase name unchanged (conservative fallback).
    """
    if phase_name in EngagementStateMachine.STATES:
        return phase_name
    return PHASE_TO_STATE_MAP.get(phase_name, phase_name)


def resolve_phase_for_state(state_name: str) -> str:
    """Translate a state machine state name back to an agent phase name.

    Returns the canonical agent phase name for the given state machine state.
    If the state is already a valid phase name, returns it as-is.
    If unknown, returns the state name unchanged (conservative fallback).

    Note: Multiple phases map to the same state (e.g. "scan", "deep_scan",
    "repo_scan" → "scanning"). The canonical (first) phase is returned.
    """
    # Build reverse map keeping the first canonical phase for each state
    _reverse_map: dict[str, str] = {}
    for phase, sm_state in PHASE_TO_STATE_MAP.items():
        if sm_state not in _reverse_map:
            _reverse_map[sm_state] = phase
    return _reverse_map.get(state_name, state_name)


class EngagementStateMachine:
    """
    Enforces valid engagement state transitions and records history
    """

    # Valid engagement states
    STATES = [
        "created",
        "recon",
        "scanning",
        "analyzing",
        "reporting",
        "complete",
        "failed",
        "paused",
    ]

    # Valid state transitions
    TRANSITIONS = {
        "created": ["recon", "failed", "paused"],
        "recon": ["scanning", "failed", "paused"],
        "scanning": ["analyzing", "failed", "paused"],
        "analyzing": ["reporting", "recon", "scanning", "failed", "paused"],
        "reporting": ["complete", "failed", "paused"],
        "paused": ["recon", "scanning", "analyzing", "reporting", "failed"],
        "failed": [],
        "complete": [],
    }

    def __init__(
        self,
        engagement_id: str,
        db_connection_string: str | None = None,
        current_state: str = "created",
        connection: psycopg2.extensions.connection | None = None,
    ):
        """
        Initialize State Machine

        Args:
            engagement_id: Engagement ID
            db_connection_string: PostgreSQL connection string (deprecated, use connection instead)
            current_state: Current engagement state
            connection: External connection for transaction support
        """
        # Validate UUID format to prevent PostgreSQL errors
        self.engagement_id = validate_uuid(engagement_id, "engagement_id")
        self._external_conn = connection
        self.current_state = None  # Will be set properly after None-handling below
        # WebSocket publisher removed (M-07 consolidation).
        # All events go through SSE via StreamManager.

        # Deprecation warning for raw connection string — always use pool
        if db_connection_string is not None:
            logger.warning(
                "db_connection_string is deprecated for engagement %s — "
                "connection pooling is preferred. Remove this parameter.",
                engagement_id,
            )

        # Handle None — defer resolution to first transition() call
        # where it will be queried under the FOR UPDATE lock, avoiding
        # a TOCTOU race between constructor and first transition.
        if current_state is None:
            self.current_state = None  # Mark as unresolved
        else:
            resolved_state = current_state
            if resolved_state == "awaiting_approval":
                logger.warning(
                    "Engagement %s has deprecated 'awaiting_approval' state — mapping to 'recon'",
                    engagement_id,
                )
                resolved_state = "recon"

            if resolved_state not in self.STATES:
                raise ValueError(f"Invalid state: {resolved_state}")

            self.current_state = resolved_state

    def _resolve_state_if_needed(self):
        """Lazily resolve state from DB if it was None on construction.

        Called at the start of transition() and chain_transition() so
        the FOR UPDATE lock is already held, preventing TOCTOU races.
        """
        if self.current_state is not None:
            return
        conn = self._get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT status FROM engagements WHERE id = %s", (self.engagement_id,)
            )
            row = c.fetchone()
            c.close()
            resolved = row[0] if row else "created"
        except (psycopg2.Error, DatabaseConnectionError) as e:
            logger.error(
                "Database error resolving state for engagement %s: %s",
                self.engagement_id,
                e,
            )
            raise  # Re-raise DB outages — don't silently mask them
        except (IndexError, TypeError) as e:
            logger.warning(
                "Unexpected row format for engagement %s, defaulting to 'created': %s",
                self.engagement_id,
                e,
            )
            resolved = "created"
        finally:
            self._release_connection(conn)

        if resolved == "awaiting_approval":
            logger.warning(
                "Engagement %s has deprecated 'awaiting_approval' state — mapping to 'recon'",
                self.engagement_id,
            )
            resolved = "recon"
        self.current_state = resolved

    def _get_connection(self):
        """Get a database connection (external or from pool).

        Always uses the connection pool. The deprecated _db_conn_string
        raw-connection path has been removed — all connections must go
        through the pool to prevent connection leaks.
        """
        if self._external_conn:
            return self._external_conn
        return get_db().get_connection()

    def _release_connection(self, conn):
        """Release connection back to pool.

        Never releases an external connection — the caller owns its lifecycle.
        Always returns connections to the pool (the deprecated raw-connection
        close() path has been removed).
        """
        if conn and not self._external_conn:
            get_db().release_connection(conn)

    def transition(
        self, new_state: str, reason: str | None = None, trace_id: str | None = None
    ):
        """
        Enforce valid state transitions with atomic locking and causality tracking.

        Uses SELECT ... FOR UPDATE within a transaction to prevent concurrent
        workers from racing on the same engagement's state.

        Args:
            new_state: Target state
            reason: Reason for transition (human-readable)
            trace_id: Distributed trace ID for causality chain

        Raises:
            InvalidStateTransitionError: If transition is invalid
        """
        # Validate new state
        if new_state not in self.STATES:
            raise ValueError(f"Invalid state: {new_state}")

        # Resolve lazy state immediately so can_transition_to works.
        # The real validation happens again under FOR UPDATE in
        # _persist_state_and_budget, so there's no TOCTOU issue.
        self._resolve_state_if_needed()

        # Check if transition is valid (quick pre-check — final check under lock)
        if not self.can_transition_to(new_state):
            raise InvalidStateTransitionError(
                f"Invalid transition from {self.current_state} to {new_state}. "
                f"Valid transitions: {self.TRANSITIONS[self.current_state]}"
            )

        old_state = self.current_state

        # Persist state transition atomically with FOR UPDATE locking
        self._persist_state_and_budget(
            from_state=old_state,
            to_state=new_state,
            reason=reason or f"Transition to {new_state}",
            trace_id=trace_id,
        )

        # Update current state
        self.current_state = new_state

        # WebSocket state transition publishing removed (M-07 consolidation).
        # All events go through SSE via StreamManager.

    def _persist_state_and_budget(
        self, from_state: str, to_state: str, reason: str, trace_id: str | None = None
    ):
        """
        Atomically record state transition and update loop budget if needed.
        Uses SELECT ... FOR UPDATE to prevent concurrent state races.

        Args:
            from_state: Source state
            to_state: Target state
            reason: Reason for transition
            trace_id: Distributed trace ID for causality chain
        """
        conn = None
        cursor = None

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Lock the engagement row to prevent concurrent state transitions
            cursor.execute(
                "SELECT status FROM engagements WHERE id = %s FOR UPDATE",
                (self.engagement_id,),
            )
            locked_row = cursor.fetchone()
            if not locked_row:
                raise ValueError(f"Engagement {self.engagement_id} not found")

            current_db_state = locked_row[0]
            if current_db_state != from_state:
                # State was already changed by another worker — this is a race.
                # The FOR UPDATE lock guarantees we have the latest value, so
                # we reject the transition rather than silently accepting the
                # new from_state. The caller should retry with fresh state.
                logger.error(
                    "State race detected: expected %s, actual %s for engagement %s. "
                    "Rejecting transition to %s — another worker changed state.",
                    from_state,
                    current_db_state,
                    self.engagement_id,
                    to_state,
                )
                raise InvalidStateTransitionError(
                    f"Race: engagement {self.engagement_id} is {current_db_state}, "
                    f"not {from_state}. Another worker changed state first."
                )

            # Record state transition with trace_id for causality chain
            transition_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO engagement_states (
                    id, engagement_id, from_state, to_state, reason, trace_id, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, NOW()
                )
                """,
                (
                    transition_id,
                    self.engagement_id,
                    current_db_state,
                    to_state,
                    reason,
                    trace_id,
                ),
            )

            # Update engagement status with WHERE clause for safety
            cursor.execute(
                """
                UPDATE engagements
                SET status = %s, updated_at = NOW()
                WHERE id = %s AND status = %s
                """,
                (to_state, self.engagement_id, current_db_state),
            )

            if cursor.rowcount == 0:
                # Someone else changed state after our FOR UPDATE lock —
                # this shouldn't happen, but guard against it
                conn.rollback()
                raise InvalidStateTransitionError(
                    f"Concurrent state change detected for engagement {self.engagement_id}"
                )

            # If looping back from analyzing to recon, enforce max_cycles.
            # NOTE: The budget counter (current_cycles) is NOT incremented here.
            # LoopBudgetManager.consume() is the sole owner of budget tracking.
            # This block only checks max_cycles as a safety guard — it reads
            # the current DB value (which LoopBudgetManager.persist_to_db()
            # has already written) and rejects the transition if budget is
            # exhausted, preventing a double-increment bug where both
            # state_machine and LoopBudgetManager increased the counter.
            if from_state == "analyzing" and to_state == "recon":
                cursor.execute(
                    "SELECT current_cycles, max_cycles FROM loop_budgets WHERE engagement_id = %s",
                    (self.engagement_id,),
                )
                lb_row = cursor.fetchone()
                current_cycles = lb_row[0] if lb_row else 0
                max_cycles = lb_row[1] if lb_row else 5
                if current_cycles >= max_cycles:
                    raise InvalidStateTransitionError(
                        f"Loop budget exhausted for engagement {self.engagement_id}: "
                        f"{current_cycles}/{max_cycles} cycles used."
                    )

            conn.commit()

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(
                "Failed to persist state transition for engagement %s: %s",
                self.engagement_id,
                e,
            )
            raise
        finally:
            if cursor:
                cursor.close()
            self._release_connection(conn)

    def get_transition_history(self) -> list[dict]:
        """
        Get transition history for engagement

        Returns:
            List of transition records
        """
        conn = self._get_connection()
        cursor = None

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT from_state, to_state, reason, created_at
                FROM engagement_states
                WHERE engagement_id = %s
                ORDER BY created_at ASC
                """,
                (self.engagement_id,),
            )

            rows = cursor.fetchall()
            cursor.close()

            history = []
            for row in rows:
                history.append(
                    {
                        "from_state": row[0],
                        "to_state": row[1],
                        "reason": row[2],
                        "timestamp": row[3].isoformat() if row[3] else None,
                    }
                )

            return history

        finally:
            if cursor:
                cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def get_valid_transitions(self) -> list[str]:
        """
        Get valid transitions from current state

        Returns:
            List of valid target states
        """
        return self.TRANSITIONS.get(self.current_state, [])

    def safe_transition(self, new_state: str, reason: str | None = None) -> bool:
        """
        Attempt a state transition, but silently skip if the current state
        has no outgoing transitions (e.g. already 'failed' or 'complete').
        Returns True if the transition was applied, False if skipped.
        """
        if new_state not in self.STATES:
            logger.warning(
                "safe_transition: '%s' is not a valid state for engagement %s — skipping",
                new_state,
                self.engagement_id,
            )
            return False
        if not self.can_transition_to(new_state):
            logger.warning(
                "Skipping transition %s -> %s for engagement %s "
                "(no valid outgoing transitions from current state — engagement may be in terminal state)",
                self.current_state,
                new_state,
                self.engagement_id,
            )
            return False
        self.transition(new_state, reason)
        return True

    def chain_transition(
        self, states: list[tuple[str, str]], trace_id: str | None = None
    ) -> str:
        """
        Perform multiple state transitions in a single database transaction.
        Each element of states is a (new_state, reason) tuple.

        This avoids phantom intermediate states when fast-forwarding through
        multiple phases (e.g., recon → scanning → analyzing → reporting).

        Args:
            states: List of (new_state, reason) tuples to chain through

        Returns:
            The final state after all transitions

        Raises:
            InvalidStateTransitionError: If any transition in the chain is invalid
        """
        if not states:
            return self.current_state

        # Resolve lazy state so terminal-state check is accurate.
        # The FOR UPDATE lock in the DB ensures freshness.
        self._resolve_state_if_needed()

        if self.current_state in ("complete", "failed"):
            logger.warning(
                "chain_transition called on engagement %s in terminal state %s — skipping",
                self.engagement_id,
                self.current_state,
            )
            return self.current_state

        conn = self._get_connection()
        cursor = None
        try:
            cursor = conn.cursor()

            # Lock the engagement row to prevent concurrent state transitions
            cursor.execute(
                "SELECT status FROM engagements WHERE id = %s FOR UPDATE",
                (self.engagement_id,),
            )
            locked_row = cursor.fetchone()
            if not locked_row:
                raise ValueError(f"Engagement {self.engagement_id} not found")

            db_current = locked_row[0]
            if db_current in ("complete", "failed"):
                logger.warning(
                    "chain_transition: engagement %s already in terminal state %s — skipping",
                    self.engagement_id,
                    db_current,
                )
                conn.rollback()
                return db_current

            # Sync local state with DB to ensure websocket events use the correct from_state
            self.current_state = db_current
            current = db_current
            for new_state, reason in states:
                if new_state not in self.STATES:
                    raise ValueError(f"Invalid state: {new_state}")
                if new_state not in self.TRANSITIONS.get(current, []):
                    raise InvalidStateTransitionError(
                        f"Invalid transition from {current} to {new_state}. "
                        f"Valid transitions: {self.TRANSITIONS[current]}"
                    )
                # Insert into engagement_states history
                transition_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO engagement_states (id, engagement_id, from_state, to_state, reason, trace_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        transition_id,
                        self.engagement_id,
                        current,
                        new_state,
                        reason,
                        trace_id,
                    ),
                )
                current = new_state

            # Update the engagement's current status with WHERE guard
            final_state = states[-1][0]
            cursor.execute(
                "UPDATE engagements SET status = %s, updated_at = NOW() WHERE id = %s AND status = %s",
                (final_state, self.engagement_id, db_current),
            )

            if cursor.rowcount == 0:
                conn.rollback()
                raise InvalidStateTransitionError(
                    f"Concurrent state change detected for engagement {self.engagement_id}"
                )

            # If looping through analyze→recon in the chain, enforce max_cycles.
            # NOTE: The budget counter (current_cycles) is NOT incremented here.
            # LoopBudgetManager.consume() is the sole owner of budget tracking.
            # This block only checks max_cycles as a safety guard (same rationale
            # as _persist_state_and_budget) — prevents double-increment bug.
            recon_loop_count = sum(
                1 for f, t in states if f == "analyzing" and t == "recon"
            )
            if recon_loop_count > 0:
                cursor.execute(
                    "SELECT current_cycles, max_cycles FROM loop_budgets WHERE engagement_id = %s",
                    (self.engagement_id,),
                )
                lb_row = cursor.fetchone()
                current_cycles = lb_row[0] if lb_row else 0
                max_cycles = lb_row[1] if lb_row else 5
                if current_cycles + recon_loop_count > max_cycles:
                    conn.rollback()
                    raise InvalidStateTransitionError(
                        f"Loop budget exhausted for engagement {self.engagement_id}: "
                        f"{current_cycles + recon_loop_count}/{max_cycles} cycles required."
                    )

            conn.commit()

            # WebSocket chain transition publishing removed (M-07 consolidation).
            # All events go through SSE via StreamManager.

            self.current_state = final_state
            return final_state
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(
                "chain_transition failed for engagement %s: %s", self.engagement_id, e
            )
            raise
        except ValueError:
            if conn:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            self._release_connection(conn)

    def can_transition_to(self, new_state: str) -> bool:
        """
        Check if transition to new_state is valid from current state

        Args:
            new_state: Target state to transition to

        Returns:
            True if transition is valid, False otherwise
        """
        return new_state in self.TRANSITIONS.get(self.current_state, [])
