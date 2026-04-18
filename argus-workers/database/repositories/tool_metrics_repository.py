"""
Tool Metrics Repository - Records and queries tool performance metrics

Requirements: 22.1, 22.2
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional
from datetime import datetime, timedelta
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
            conn.close()
    
    def get_performance_stats(self, days: int = 7) -> List[Dict]:
        """
        Get performance statistics for all tools over the last N days
        
        Args:
            days: Number of days to look back (default: 7)
            
        Returns:
            List of dictionaries with tool performance statistics
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(
                """
                SELECT 
                    tool_name,
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                    ROUND(AVG(duration_ms)::numeric, 2) as avg_duration_ms,
                    ROUND((SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) * 100)::numeric, 2) as success_rate,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms
                FROM tool_metrics
                WHERE created_at >= NOW() - INTERVAL '%s days'
                GROUP BY tool_name
                ORDER BY total_executions DESC
                """,
                (days,)
            )
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
            
        finally:
            cursor.close()
            conn.close()
    
    def get_tool_stats(self, tool_name: str, days: int = 7) -> Optional[Dict]:
        """
        Get performance statistics for a specific tool
        
        Args:
            tool_name: Name of the tool
            days: Number of days to look back (default: 7)
            
        Returns:
            Dictionary with tool performance statistics or None
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute(
                """
                SELECT 
                    tool_name,
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                    ROUND(AVG(duration_ms)::numeric, 2) as avg_duration_ms,
                    ROUND((SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) * 100)::numeric, 2) as success_rate,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms
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
            conn.close()
    
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
            conn.close()
    
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
