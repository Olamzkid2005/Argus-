"""
Repository for execution logs and spans

Provides database operations for the execution_logs and execution_spans tables.
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional
from datetime import datetime
import uuid


class TracingRepository:
    """
    Repository for execution_logs and execution_spans tables.
    """
    
    def __init__(self, connection_string: str):
        """
        Initialize repository with database connection string.
        
        Args:
            connection_string: PostgreSQL connection string
        """
        self.connection_string = connection_string
    
    def _get_connection(self):
        """Get a database connection"""
        return psycopg2.connect(self.connection_string)
    
    # =========================================================================
    # Execution Logs
    # =========================================================================
    
    def insert_log(
        self,
        trace_id: str,
        event_type: str,
        message: str,
        engagement_id: str = None,
        metadata: Dict = None
    ) -> Dict:
        """
        Insert an execution log entry.
        
        Args:
            trace_id: Trace ID for correlation
            event_type: Type of event
            message: Log message
            engagement_id: Optional engagement ID
            metadata: Optional metadata dictionary
            
        Returns:
            Inserted log entry
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                INSERT INTO execution_logs 
                (engagement_id, trace_id, event_type, message, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (
                engagement_id,
                trace_id,
                event_type,
                message,
                metadata or {},
            ))
            
            row = cursor.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            cursor.close()
            conn.close()
    
    def find_logs_by_trace_id(self, trace_id: str) -> List[Dict]:
        """
        Find all logs for a trace ID.
        
        Args:
            trace_id: Trace ID to search for
            
        Returns:
            List of log entries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT * FROM execution_logs
                WHERE trace_id = %s
                ORDER BY created_at ASC
            """, (trace_id,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            conn.close()
    
    def find_logs_by_engagement_id(
        self,
        engagement_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """
        Find logs for an engagement.
        
        Args:
            engagement_id: Engagement ID
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            List of log entries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT * FROM execution_logs
                WHERE engagement_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (engagement_id, limit, offset))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            conn.close()
    
    def find_logs_by_event_type(
        self,
        event_type: str,
        limit: int = 100
    ) -> List[Dict]:
        """
        Find logs by event type.
        
        Args:
            event_type: Event type to filter by
            limit: Maximum number of results
            
        Returns:
            List of log entries
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT * FROM execution_logs
                WHERE event_type = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (event_type, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            conn.close()
    
    # =========================================================================
    # Execution Spans
    # =========================================================================
    
    def insert_span(
        self,
        trace_id: str,
        span_name: str,
        duration_ms: int
    ) -> Dict:
        """
        Insert an execution span.
        
        Args:
            trace_id: Trace ID for correlation
            span_name: Name of the span
            duration_ms: Duration in milliseconds
            
        Returns:
            Inserted span entry
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                INSERT INTO execution_spans 
                (trace_id, span_name, duration_ms)
                VALUES (%s, %s, %s)
                RETURNING *
            """, (
                trace_id,
                span_name,
                duration_ms,
            ))
            
            row = cursor.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            cursor.close()
            conn.close()
    
    def find_spans_by_trace_id(self, trace_id: str) -> List[Dict]:
        """
        Find all spans for a trace ID.
        
        Args:
            trace_id: Trace ID to search for
            
        Returns:
            List of span entries ordered by timestamp
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT * FROM execution_spans
                WHERE trace_id = %s
                ORDER BY created_at ASC
            """, (trace_id,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            conn.close()
    
    # =========================================================================
    # Timeline (Combined Logs + Spans)
    # =========================================================================
    
    def get_execution_timeline(self, trace_id: str) -> List[Dict]:
        """
        Get combined execution timeline for a trace.
        Merges logs and spans, ordered by timestamp.
        
        Args:
            trace_id: Trace ID
            
        Returns:
            List of timeline events
        """
        logs = self.find_logs_by_trace_id(trace_id)
        spans = self.find_spans_by_trace_id(trace_id)
        
        timeline = []
        
        for log in logs:
            timeline.append({
                "type": "log",
                "id": str(log["id"]),
                "event_type": log["event_type"],
                "message": log["message"],
                "metadata": log.get("metadata"),
                "timestamp": log["created_at"].isoformat() if log.get("created_at") else None,
            })
        
        for span in spans:
            timeline.append({
                "type": "span",
                "id": str(span["id"]),
                "span_name": span["span_name"],
                "duration_ms": span["duration_ms"],
                "timestamp": span["created_at"].isoformat() if span.get("created_at") else None,
            })
        
        # Sort by timestamp
        timeline.sort(key=lambda x: x.get("timestamp") or "")
        
        return timeline
    
    # =========================================================================
    # Tool Metrics
    # =========================================================================
    
    def insert_tool_metric(
        self,
        tool_name: str,
        duration_ms: int,
        success: bool
    ) -> Dict:
        """
        Insert a tool execution metric.
        
        Args:
            tool_name: Name of the tool
            duration_ms: Duration in milliseconds
            success: Whether execution succeeded
            
        Returns:
            Inserted metric entry
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                INSERT INTO tool_metrics 
                (tool_name, duration_ms, success)
                VALUES (%s, %s, %s)
                RETURNING *
            """, (
                tool_name,
                duration_ms,
                success,
            ))
            
            row = cursor.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            cursor.close()
            conn.close()
    
    def get_tool_performance_stats(self, days: int = 7) -> List[Dict]:
        """
        Get tool performance statistics over the last N days.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            List of tool performance statistics
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT 
                    tool_name,
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                    AVG(duration_ms) as avg_duration_ms,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms
                FROM tool_metrics
                WHERE created_at >= NOW() - INTERVAL '%s days'
                GROUP BY tool_name
                ORDER BY total_executions DESC
            """, (days,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            cursor.close()
            conn.close()
