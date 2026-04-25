"""
Tool Metrics Repository - Records and queries tool performance metrics

Requirements: 22.1, 22.2
"""
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional
import uuid

from database.repositories.base import BaseRepository


class ToolMetricsRepository(BaseRepository):
    """
    Repository for tool_metrics table operations.
    
    Records tool execution metrics and calculates performance statistics.
    """
    
    table_name = "tool_metrics"
    id_column = "id"
    
    def record_metric(
        self,
        tool_name: str,
        duration_ms: int,
        success: bool
    ) -> str:
        """
        Record a tool execution metric
        
        Args:
            tool_name: Name of the tool (e.g., 'nuclei', 'httpx')
            duration_ms: Execution duration in milliseconds
            success: Whether the execution succeeded
            
        Returns:
            The ID of the created metric record
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            metric_id = str(uuid.uuid4())
            
            cursor.execute(
                """
                INSERT INTO tool_metrics (id, tool_name, duration_ms, success, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (metric_id, tool_name, duration_ms, success)
            )
            
            result = cursor.fetchone()
            conn.commit()
            
            return result[0] if result else metric_id
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)
    
    def get_recent_executions(self, tool_name: str, limit: int = 100) -> List[Dict]:
        """
        Get recent executions for a specific tool
        
        Args:
            tool_name: Name of the tool
            limit: Maximum number of records to return
            
        Returns:
            List of execution records
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(
                """
                SELECT id, tool_name, duration_ms, success, created_at
                FROM tool_metrics
                WHERE tool_name = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (tool_name, limit)
            )
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
            
        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)
    
    def get_performance_stats(self, days: int = 1) -> List[Dict]:
        """
        Get performance statistics for all tools within the specified period.

        Args:
            days: Number of days to look back

        Returns:
            List of tool performance stat dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT
                    tool_name,
                    COUNT(*) AS total_executions,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
                    AVG(duration_ms) AS avg_duration_ms,
                    ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 2) AS success_rate
                FROM tool_metrics
                WHERE created_at >= NOW() - INTERVAL '%s days'
                GROUP BY tool_name
                ORDER BY tool_name
                """,
                (days,)
            )

            return [dict(row) for row in cursor.fetchall()]

        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def get_tool_stats(self, tool_name: str, days: int = 1) -> Optional[Dict]:
        """
        Get performance statistics for a specific tool.

        Args:
            tool_name: Name of the tool
            days: Number of days to look back

        Returns:
            Tool performance stat dictionary, or None if no data
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT
                    tool_name,
                    COUNT(*) AS total_executions,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
                    AVG(duration_ms) AS avg_duration_ms,
                    ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 2) AS success_rate
                FROM tool_metrics
                WHERE tool_name = %s AND created_at >= NOW() - INTERVAL '%s days'
                GROUP BY tool_name
                """,
                (tool_name, days)
            )

            row = cursor.fetchone()
            return dict(row) if row else None

        finally:
            cursor.close()
            if not self._external_conn:
                self._release_connection(conn)

    def cleanup_old_metrics(self, days: int = 30) -> int:
        """
        Delete metrics older than specified days
        
        Args:
            days: Delete metrics older than this many days
            
        Returns:
            Number of deleted records
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                DELETE FROM tool_metrics
                WHERE created_at < NOW() - INTERVAL '%s days'
                """,
                (days,)
            )
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            return deleted_count
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
