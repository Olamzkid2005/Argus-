"""
Engagement State Machine - Enforces valid state transitions

Uses the shared connection pool from database/connection.py.
Supports passing an external connection for transaction support.
"""
import logging
import uuid

import psycopg2

from database.connection import connect, get_db
from utils.validation import validate_uuid

logger = logging.getLogger(__name__)


class InvalidStateTransitionError(Exception):
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

    def __init__(self, engagement_id: str, db_connection_string: str | None = None,
                 current_state: str = "created", connection: psycopg2.extensions.connection | None = None):
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
        self._db_conn_string = db_connection_string
        self._external_conn = connection
        self.current_state = None  # Will be set properly after None-handling below
        # Optional websocket publisher — when set, every transition() also emits
        # a frontend event so the orchestrator doesn't need duplicate publish calls.
        self._ws_publisher = None

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
            c.execute("SELECT status FROM engagements WHERE id = %s", (self.engagement_id,))
            row = c.fetchone()
            c.close()
            resolved = row[0] if row else "created"
        except Exception as e:
            logger.warning(
                "Could not query state for engagement %s, defaulting to 'created': %s",
                self.engagement_id, e,
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
        """Get a database connection (external or from pool)"""
        if self._external_conn:
            return self._external_conn
        if self._db_conn_string:
            return connect(self._db_conn_string)
        return get_db().get_connection()

    def _release_connection(self, conn):
        """Release connection back to pool or close raw connections.
        
        Never releases an external connection — the caller owns its lifecycle.
        """
        if conn and not self._external_conn:
            if self._db_conn_string:
                conn.close()
            else:
                get_db().release_connection(conn)

    def transition(self, new_state: str, reason: str | None = None, trace_id: str | None = None):
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

        # Notify frontend via websocket publisher if configured.
        if self._ws_publisher:
            try:
                self._ws_publisher.publish_state_transition(
                    engagement_id=self.engagement_id,
                    from_state=old_state,
                    to_state=new_state,
                    reason=reason or f"Transition to {new_state}",
                )
            except (ConnectionError, OSError, ValueError) as e:
                logger.debug("Failed to publish state transition for %s: %s", self.engagement_id, e)

    def _persist_state_and_budget(self, from_state: str, to_state: str, reason: str, trace_id: str | None = None):
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
                (self.engagement_id,)
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
                    from_state, current_db_state, self.engagement_id, to_state
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
                (transition_id, self.engagement_id, current_db_state, to_state,
                 reason, trace_id)
            )

            # Update engagement status with WHERE clause for safety
            cursor.execute(
                """
                UPDATE engagements
                SET status = %s, updated_at = NOW()
                WHERE id = %s AND status = %s
                """,
                (to_state, self.engagement_id, current_db_state)
            )

            if cursor.rowcount == 0:
                # Someone else changed state after our FOR UPDATE lock —
                # this shouldn't happen, but guard against it
                conn.rollback()
                raise InvalidStateTransitionError(
                    f"Concurrent state change detected for engagement {self.engagement_id}"
                )

            # If looping back from analyzing to recon, increment budget.
            # Use INSERT ... ON CONFLICT DO UPDATE (UPSERT) so the row is
            # auto-created for non-scheduled engagements that were created
            # without an explicit loop_budgets INSERT.
            # Enforce max_cycles to prevent infinite looping.
            if from_state == "analyzing" and to_state == "recon":
                # First, read current cycles to check against max
                cursor.execute(
                    "SELECT current_cycles, max_cycles FROM loop_budgets WHERE engagement_id = %s",
                    (self.engagement_id,)
                )
                lb_row = cursor.fetchone()
                current_cycles = lb_row[0] if lb_row else 0
                max_cycles = lb_row[1] if lb_row else 5
                if current_cycles >= max_cycles:
                    raise InvalidStateTransitionError(
                        f"Loop budget exhausted for engagement {self.engagement_id}: "
                        f"{current_cycles}/{max_cycles} cycles used."
                    )
                cursor.execute(
                    """
                    INSERT INTO loop_budgets (id, engagement_id, max_cycles, max_depth,
                                               current_cycles, current_depth, created_at)
                    VALUES (%s, %s, %s, 3, 1, 0, NOW())
                    ON CONFLICT (engagement_id)
                    DO UPDATE SET
                        current_cycles = loop_budgets.current_cycles + 1,
                        updated_at = NOW()
                    """,
                    (str(uuid.uuid4()), self.engagement_id, max_cycles)
                )

            conn.commit()

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"Failed to persist state transition for engagement {self.engagement_id}: {e}")
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
                new_state, self.engagement_id,
            )
            return False
        if not self.can_transition_to(new_state):
            logger.warning(
                "Skipping transition %s -> %s for engagement %s "
                "(no valid outgoing transitions from current state — engagement may be in terminal state)",
                self.current_state, new_state, self.engagement_id,
            )
            return False
        self.transition(new_state, reason)
        return True

    def chain_transition(self, states: list[tuple[str, str]], trace_id: str | None = None) -> str:
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
                self.engagement_id, self.current_state,
            )
            return self.current_state

        conn = self._get_connection()
        cursor = None
        try:
            cursor = conn.cursor()

            # Lock the engagement row to prevent concurrent state transitions
            cursor.execute(
                "SELECT status FROM engagements WHERE id = %s FOR UPDATE",
                (self.engagement_id,)
            )
            locked_row = cursor.fetchone()
            if not locked_row:
                raise ValueError(f"Engagement {self.engagement_id} not found")

            db_current = locked_row[0]
            if db_current in ("complete", "failed"):
                logger.warning(
                    "chain_transition: engagement %s already in terminal state %s — skipping",
                    self.engagement_id, db_current,
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
                    (transition_id, self.engagement_id, current, new_state, reason, trace_id)
                )
                current = new_state

            # Update the engagement's current status with WHERE guard
            final_state = states[-1][0]
            cursor.execute(
                "UPDATE engagements SET status = %s, updated_at = NOW() WHERE id = %s AND status = %s",
                (final_state, self.engagement_id, db_current)
            )

            if cursor.rowcount == 0:
                conn.rollback()
                raise InvalidStateTransitionError(
                    f"Concurrent state change detected for engagement {self.engagement_id}"
                )

            # If looping through analyze→recon in the chain, increment budget.
            # Use INSERT ... ON CONFLICT DO UPDATE (UPSERT) so the row is
            # auto-created for non-scheduled engagements that were created
            # without an explicit loop_budgets INSERT.
            # Enforce max_cycles to prevent infinite looping.
            recon_loop_count = sum(1 for f, t in states if f == "analyzing" and t == "recon")
            if recon_loop_count > 0:
                # Read current cycles to check against max
                cursor.execute(
                    "SELECT current_cycles, max_cycles FROM loop_budgets WHERE engagement_id = %s",
                    (self.engagement_id,)
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
                cursor.execute(
                    """
                    INSERT INTO loop_budgets (id, engagement_id, max_cycles, max_depth,
                                               current_cycles, current_depth, created_at)
                    VALUES (%s, %s, %s, 3, %s, 0, NOW())
                    ON CONFLICT (engagement_id)
                    DO UPDATE SET
                        current_cycles = loop_budgets.current_cycles + %s,
                        updated_at = NOW()
                    """,
                    (str(uuid.uuid4()), self.engagement_id, max_cycles, recon_loop_count, recon_loop_count),
                )

            conn.commit()

            # Publish websocket events for every intermediate state so the
            # frontend sees each step (e.g. scanning → analyzing → reporting).
            if self._ws_publisher:
                try:
                    ws_current = db_current
                    for new_state, reason in states:
                        self._ws_publisher.publish_state_transition(
                            engagement_id=self.engagement_id,
                            from_state=ws_current,
                            to_state=new_state,
                            reason=reason,
                        )
                        ws_current = new_state
                except (ConnectionError, OSError, ValueError) as e:
                    logger.debug("Failed to publish chain transition for %s: %s", self.engagement_id, e)

            self.current_state = final_state
            return final_state
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error("chain_transition failed for engagement %s: %s", self.engagement_id, e)
            raise
        except ValueError as e:
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
