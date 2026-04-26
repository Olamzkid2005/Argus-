"""
Snapshot Manager - Creates immutable state snapshots for decision-making
"""
import psycopg2
from database.connection import connect
from psycopg2.extras import Json, RealDictCursor
import uuid
from typing import Dict, List, Optional
from datetime import datetime, UTC
from decimal import Decimal


class SnapshotManager:
    """
    Creates and manages immutable state snapshots for Intelligence Engine
    """
    
    def __init__(self, db_connection_string: str):
        """
        Initialize Snapshot Manager
        
        Args:
            db_connection_string: PostgreSQL connection string
        """
        self.db_conn_string = db_connection_string
    
    def create_snapshot(self, engagement_id: str) -> Dict:
        """
        Create immutable snapshot of engagement state
        
        Uses SERIALIZABLE isolation level to ensure consistency.
        Captures: findings, attack graph, loop budget, engagement state
        
        Args:
            engagement_id: Engagement ID
            
        Returns:
            Snapshot dictionary with all state data
        """
        conn = connect(self.db_conn_string)
        
        try:
            # Set SERIALIZABLE isolation level
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE)
            
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
                (engagement_id,)
            )
            findings = [dict(row) for row in cursor.fetchall()]
            
            # Capture attack graph (attack_paths)
            cursor.execute(
                """
                SELECT 
                    id, path_nodes, risk_score, normalized_severity, created_at
                FROM attack_paths
                WHERE engagement_id = %s
                ORDER BY risk_score DESC
                """,
                (engagement_id,)
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
                (engagement_id,)
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
                (engagement_id,)
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
                "snapshot_timestamp": datetime.now(UTC).isoformat(),
            }
            
            # Convert DB-native types (e.g. Decimal) into JSON-safe values
            # before persisting and returning snapshot data.
            snapshot_data = self._to_jsonable(snapshot_data)

            # Store snapshot in database
            snapshot_id = self._store_snapshot(engagement_id, snapshot_data, cursor)
            
            conn.commit()
            
            # Add snapshot ID to data
            snapshot_data["snapshot_id"] = snapshot_id
            
            return snapshot_data
            
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to create snapshot: {e}")
        finally:
            cursor.close()
            conn.close()

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
    
    def _store_snapshot(
        self,
        engagement_id: str,
        snapshot_data: Dict,
        cursor
    ) -> str:
        """
        Store snapshot in decision_snapshots table
        
        Args:
            engagement_id: Engagement ID
            snapshot_data: Snapshot data dictionary
            cursor: Database cursor
            
        Returns:
            Snapshot ID
        """
        snapshot_id = str(uuid.uuid4())
        
        # Get next version number
        cursor.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 as next_version
            FROM decision_snapshots
            WHERE engagement_id = %s
            """,
            (engagement_id,)
        )
        version = cursor.fetchone()["next_version"]
        
        # Insert snapshot
        cursor.execute(
            """
            INSERT INTO decision_snapshots (
                id, engagement_id, version, snapshot_data, created_at
            ) VALUES (
                %s, %s, %s, %s, NOW()
            )
            """,
            (snapshot_id, engagement_id, version, Json(snapshot_data))
        )
        
        return snapshot_id
    
    def get_snapshot(self, snapshot_id: str) -> Optional[Dict]:
        """
        Retrieve snapshot by ID
        
        Args:
            snapshot_id: Snapshot ID
            
        Returns:
            Snapshot data or None if not found
        """
        conn = connect(self.db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(
                """
                SELECT id, engagement_id, version, snapshot_data, created_at
                FROM decision_snapshots
                WHERE id = %s
                """,
                (snapshot_id,)
            )
            
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            return None
            
        finally:
            cursor.close()
            conn.close()
    
    def get_latest_snapshot(self, engagement_id: str) -> Optional[Dict]:
        """
        Get latest snapshot for engagement
        
        Args:
            engagement_id: Engagement ID
            
        Returns:
            Latest snapshot data or None
        """
        conn = connect(self.db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(
                """
                SELECT id, engagement_id, version, snapshot_data, created_at
                FROM decision_snapshots
                WHERE engagement_id = %s
                ORDER BY version DESC
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
    
    def list_snapshots(self, engagement_id: str) -> List[Dict]:
        """
        List all snapshots for engagement
        
        Args:
            engagement_id: Engagement ID
            
        Returns:
            List of snapshot metadata (without full data)
        """
        conn = connect(self.db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(
                """
                SELECT id, engagement_id, version, created_at
                FROM decision_snapshots
                WHERE engagement_id = %s
                ORDER BY version DESC
                """,
                (engagement_id,)
            )
            
            return [dict(row) for row in cursor.fetchall()]
            
        finally:
            cursor.close()
            conn.close()
