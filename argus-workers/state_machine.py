"""
Engagement State Machine - Enforces valid state transitions
"""
from typing import Dict, List, Optional
from datetime import datetime
import psycopg2
from psycopg2.extras import Json
import uuid


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
    
    def __init__(self, engagement_id: str, db_connection_string: str, current_state: str = "created"):
        """
        Initialize State Machine
        
        Args:
            engagement_id: Engagement ID
            db_connection_string: PostgreSQL connection string
            current_state: Current engagement state
        """
        self.engagement_id = engagement_id
        self.db_conn_string = db_connection_string
        self.current_state = current_state
        
        if current_state not in self.STATES:
            raise ValueError(f"Invalid state: {current_state}")
    
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
        
        # Record transition
        self._record_transition(
            from_state=self.current_state,
            to_state=new_state,
            reason=reason or f"Transition to {new_state}",
        )
        
        # Update current state
        old_state = self.current_state
        self.current_state = new_state
        
        # Handle loop-back transitions
        if old_state == "analyzing" and new_state == "recon":
            self._increment_loop_budget_cycle()
    
    def can_transition_to(self, new_state: str) -> bool:
        """
        Check if transition is valid
        
        Args:
            new_state: Target state
            
        Returns:
            True if transition is valid
        """
        valid_transitions = self.TRANSITIONS.get(self.current_state, [])
        return new_state in valid_transitions
    
    def _record_transition(self, from_state: str, to_state: str, reason: str):
        """
        Record state transition in database
        
        Args:
            from_state: Source state
            to_state: Target state
            reason: Reason for transition
        """
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor()
        
        try:
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
            
        except Exception as e:
            conn.rollback()
            print(f"Failed to record transition: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def _increment_loop_budget_cycle(self):
        """
        Increment loop budget cycle counter on loop-back transition
        """
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                UPDATE loop_budgets
                SET current_cycles = current_cycles + 1
                WHERE engagement_id = %s
                """,
                (self.engagement_id,)
            )
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            print(f"Failed to increment loop budget cycle: {e}")
        finally:
            cursor.close()
            conn.close()
    
    def get_transition_history(self) -> List[Dict]:
        """
        Get transition history for engagement
        
        Returns:
            List of transition records
        """
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor()
        
        try:
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
            cursor.close()
            conn.close()
    
    def get_valid_transitions(self) -> List[str]:
        """
        Get valid transitions from current state
        
        Returns:
            List of valid target states
        """
        return self.TRANSITIONS.get(self.current_state, [])
