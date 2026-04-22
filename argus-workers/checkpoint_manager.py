"""
Checkpoint Manager - Saves and recovers from checkpoints during long scans
"""
import psycopg2
from psycopg2.extras import Json, RealDictCursor
import uuid
from typing import Dict, Optional, List
from datetime import datetime, UTC


class CheckpointManager:
    """
    Manages checkpoints for engagement recovery after worker crashes
    """
    
    def __init__(self, db_connection_string: str):
        """
        Initialize Checkpoint Manager
        
        Args:
            db_connection_string: PostgreSQL connection string
        """
        self.db_conn_string = db_connection_string
    
    def save_checkpoint(
        self,
        engagement_id: str,
        phase: str,
        data: Dict
    ) -> str:
        """
        Save checkpoint after completing a phase
        
        Args:
            engagement_id: Engagement ID
            phase: Phase name (recon, scan, analyze)
            data: Partial results data
            
        Returns:
            Checkpoint ID
        """
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor()
        
        try:
            checkpoint_id = str(uuid.uuid4())
            
            cursor.execute(
                """
                INSERT INTO checkpoints (
                    id, engagement_id, phase, data, created_at
                ) VALUES (
                    %s, %s, %s, %s, NOW()
                )
                """,
                (checkpoint_id, engagement_id, phase, Json(data))
            )
            
            conn.commit()
            
            return checkpoint_id
            
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to save checkpoint: {e}")
        finally:
            cursor.close()
            conn.close()
    
    def load_checkpoint(self, engagement_id: str) -> Optional[Dict]:
        """
        Load last checkpoint for engagement
        
        Args:
            engagement_id: Engagement ID
            
        Returns:
            Checkpoint data or None if no checkpoint exists
        """
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(
                """
                SELECT id, engagement_id, phase, data, created_at
                FROM checkpoints
                WHERE engagement_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (engagement_id,)
            )
            
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            return None
            
        finally:
            cursor.close()
            conn.close()
    
    def has_checkpoint(self, engagement_id: str) -> bool:
        """
        Check if checkpoint exists for engagement
        
        Args:
            engagement_id: Engagement ID
            
        Returns:
            True if checkpoint exists
        """
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT COUNT(*) FROM checkpoints
                WHERE engagement_id = %s
                """,
                (engagement_id,)
            )
            
            count = cursor.fetchone()[0]
            return count > 0
            
        finally:
            cursor.close()
            conn.close()
    
    def list_checkpoints(self, engagement_id: str) -> List[Dict]:
        """
        List all checkpoints for engagement
        
        Args:
            engagement_id: Engagement ID
            
        Returns:
            List of checkpoint metadata
        """
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(
                """
                SELECT id, engagement_id, phase, created_at
                FROM checkpoints
                WHERE engagement_id = %s
                ORDER BY created_at DESC
                """,
                (engagement_id,)
            )
            
            return [dict(row) for row in cursor.fetchall()]
            
        finally:
            cursor.close()
            conn.close()
    
    def delete_checkpoints(self, engagement_id: str):
        """
        Delete all checkpoints for engagement
        
        Args:
            engagement_id: Engagement ID
        """
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                DELETE FROM checkpoints
                WHERE engagement_id = %s
                """,
                (engagement_id,)
            )
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to delete checkpoints: {e}")
        finally:
            cursor.close()
            conn.close()
    
    def resume_from_checkpoint(self, engagement_id: str) -> Optional[Dict]:
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
        
        return {
            "engagement_id": engagement_id,
            "resume_phase": checkpoint["phase"],
            "partial_results": checkpoint["data"],
            "checkpoint_timestamp": checkpoint["created_at"].isoformat() if checkpoint["created_at"] else None,
        }
    
    def get_resume_plan(self, engagement_id: str) -> Optional[Dict]:
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
        
        try:
            current_idx = phases.index(phase)
        except ValueError:
            current_idx = 0
        
        next_phase = phases[current_idx + 1] if current_idx + 1 < len(phases) else None
        
        return {
            "engagement_id": engagement_id,
            "completed_phase": phase,
            "next_phase": next_phase,
            "partial_results": data,
            "remaining_phases": phases[current_idx + 1:] if next_phase else [],
            "checkpoint_timestamp": checkpoint["created_at"].isoformat() if checkpoint["created_at"] else None,
            "can_resume": True,
        }
    
    def cleanup_old_checkpoints(self, max_age_days: int = 7) -> int:
        """
        Delete checkpoints older than specified age.
        
        Args:
            max_age_days: Maximum age in days
            
        Returns:
            Number of checkpoints deleted
        """
        from datetime import datetime, timedelta
        
        conn = psycopg2.connect(self.db_conn_string)
        cursor = conn.cursor()
        
        try:
            cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
            
            cursor.execute(
                """
                DELETE FROM checkpoints
                WHERE created_at < %s
                """,
                (cutoff,)
            )
            
            conn.commit()
            return cursor.rowcount
            
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to cleanup checkpoints: {e}")
        finally:
            cursor.close()
            conn.close()


class CheckpointContext:
    """
    Context manager for automatic checkpoint saving
    """
    
    def __init__(
        self,
        checkpoint_manager: CheckpointManager,
        engagement_id: str,
        phase: str
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
        self.results = {}
    
    def __enter__(self):
        """Enter context"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Save checkpoint on exit if no exception"""
        if exc_type is None:
            # No exception - save checkpoint
            self.checkpoint_manager.save_checkpoint(
                self.engagement_id,
                self.phase,
                self.results
            )
    
    def add_result(self, key: str, value):
        """
        Add result to checkpoint data
        
        Args:
            key: Result key
            value: Result value
        """
        self.results[key] = value
