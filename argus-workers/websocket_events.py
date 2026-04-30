"""
WebSocket Events Publisher

Publishes real-time events to Redis for WebSocket distribution.
Used by Python workers to notify the frontend of findings, state changes,
and other engagement updates.

Supports event batching and severity-based filtering.

Requirements: 31.2, 31.3, 31.4
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import redis

logger = logging.getLogger(__name__)


class WebSocketEventPublisher:
    """
    Publishes events to Redis for WebSocket distribution.
    
    Events are stored in Redis lists for polling and published
    to Redis channels for active subscribers.
    
    Features event batching to reduce Redis overhead and
    supports filtering by severity/type.
    """
    
    # Event types
    EVENT_FINDING_DISCOVERED = "finding_discovered"
    EVENT_STATE_TRANSITION = "state_transition"
    EVENT_RATE_LIMIT = "rate_limit_event"
    EVENT_TOOL_EXECUTED = "tool_executed"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_COMPLETED = "job_completed"
    EVENT_SCANNER_ACTIVITY = "scanner_activity"
    EVENT_ERROR = "error"
    EVENT_AGENT_DECISION = "agent_decision"
    
    # Severity levels
    SEVERITY_CRITICAL = "CRITICAL"
    SEVERITY_HIGH = "HIGH"
    SEVERITY_MEDIUM = "MEDIUM"
    SEVERITY_LOW = "LOW"
    SEVERITY_INFO = "INFO"
    
    # Redis configuration
    EVENTS_TTL = 300  # 5 minutes
    MAX_EVENTS = 100
    
    # Batching configuration
    BATCH_SIZE = 10
    BATCH_INTERVAL_MS = 100
    
    def __init__(self, redis_url: str = None):
        """
        Initialize the WebSocket event publisher.
        
        Args:
            redis_url: Redis connection URL (defaults to REDIS_URL env var)
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._redis = None
        self._batch_buffer: Dict[str, List[Dict[str, Any]]] = {}
        self._last_flush = time.time()
    
    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection"""
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url)
        return self._redis
    
    def _get_channel(self, engagement_id: str) -> str:
        """Get Redis channel name for an engagement"""
        return f"ws:engagement:{engagement_id}"
    
    def _get_events_key(self, engagement_id: str) -> str:
        """Get Redis key for events list"""
        return f"events:engagement:{engagement_id}"
    
    def _get_state_key(self, engagement_id: str) -> str:
        """Get Redis key for current state"""
        return f"state:engagement:{engagement_id}"
    
    def _should_publish(self, event: Dict[str, Any], min_severity: Optional[str] = None) -> bool:
        """
        Check if event should be published based on severity filter.
        
        Args:
            event: Event dictionary
            min_severity: Minimum severity to publish (CRITICAL, HIGH, MEDIUM, LOW, INFO)
            
        Returns:
            True if event should be published
        """
        if not min_severity:
            return True
        
        severity_order = [self.SEVERITY_INFO, self.SEVERITY_LOW, self.SEVERITY_MEDIUM, 
                         self.SEVERITY_HIGH, self.SEVERITY_CRITICAL]
        
        event_severity = event.get("data", {}).get("severity", self.SEVERITY_INFO)
        
        try:
            return severity_order.index(event_severity) >= severity_order.index(min_severity)
        except ValueError:
            return True
    
    def _publish_event(self, event: Dict[str, Any], min_severity: Optional[str] = None) -> None:
        """
        Publish an event to Redis.
        
        Args:
            event: Event dictionary with type, engagement_id, timestamp, and data
            min_severity: Optional minimum severity filter
        """
        engagement_id = event.get("engagement_id")
        if not engagement_id:
            raise ValueError("Event must have engagement_id")
        
        # Check severity filter
        if not self._should_publish(event, min_severity):
            return
        
        # Store in Redis list for polling
        events_key = self._get_events_key(engagement_id)
        self.redis.lpush(events_key, json.dumps(event))
        self.redis.ltrim(events_key, 0, self.MAX_EVENTS - 1)
        self.redis.expire(events_key, self.EVENTS_TTL)
        
        # Publish to channel for active subscribers
        channel = self._get_channel(engagement_id)
        self.redis.publish(channel, json.dumps(event))
    
    def _add_to_batch(self, event: Dict[str, Any]) -> None:
        """Add event to batch buffer"""
        engagement_id = event.get("engagement_id")
        if engagement_id not in self._batch_buffer:
            self._batch_buffer[engagement_id] = []
        self._batch_buffer[engagement_id].append(event)
    
    def flush_batches(self, min_severity: Optional[str] = None) -> None:
        """
        Flush all batched events to Redis.
        
        Args:
            min_severity: Optional minimum severity filter
        """
        if not self._batch_buffer:
            return
        
        for engagement_id, events in self._batch_buffer.items():
            if not events:
                continue
            
            events_key = self._get_events_key(engagement_id)
            channel = self._get_channel(engagement_id)
            
            # Filter by severity
            filtered = [e for e in events if self._should_publish(e, min_severity)]
            
            if filtered:
                # Use pipeline for batch operations
                pipe = self.redis.pipeline()
                for event in filtered:
                    pipe.lpush(events_key, json.dumps(event))
                pipe.ltrim(events_key, 0, self.MAX_EVENTS - 1)
                pipe.expire(events_key, self.EVENTS_TTL)
                pipe.execute()
                
                # Publish last event for notifications
                if filtered:
                    self.redis.publish(channel, json.dumps(filtered[-1]))
        
        self._batch_buffer.clear()
        self._last_flush = time.time()
    
    def publish_finding(
        self,
        engagement_id: str,
        finding_id: str,
        finding_type: str,
        severity: str,
        confidence: float,
        endpoint: str,
        source_tool: str,
        use_batch: bool = True
    ) -> None:
        """
        Publish a finding discovered event.
        
        Requirements: 31.2
        
        Args:
            engagement_id: Engagement ID
            finding_id: Finding ID
            finding_type: Type of vulnerability
            severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW, INFO)
            confidence: Confidence score (0.0 - 1.0)
            endpoint: Affected endpoint URL
            source_tool: Tool that discovered the finding
            use_batch: Whether to batch this event
        """
        event = {
            "type": self.EVENT_FINDING_DISCOVERED,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "finding_id": finding_id,
                "finding_type": finding_type,
                "severity": severity,
                "confidence": confidence,
                "endpoint": endpoint,
                "source_tool": source_tool,
            }
        }
        
        if use_batch:
            self._add_to_batch(event)
            # Auto-flush if batch is large enough
            if len(self._batch_buffer.get(engagement_id, [])) >= self.BATCH_SIZE:
                self.flush_batches()
        else:
            self._publish_event(event)
    
    def publish_state_transition(
        self,
        engagement_id: str,
        from_state: str,
        to_state: str,
        reason: Optional[str] = None
    ) -> None:
        """
        Publish a state transition event.
        
        Requirements: 31.3
        
        Args:
            engagement_id: Engagement ID
            from_state: Previous state
            to_state: New state
            reason: Optional reason for transition
        """
        event = {
            "type": self.EVENT_STATE_TRANSITION,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
            }
        }
        self._publish_event(event)
        
        # Update current state in Redis
        state_key = self._get_state_key(engagement_id)
        self.redis.set(state_key, to_state)
        self.redis.expire(state_key, self.EVENTS_TTL)
    
    def publish_rate_limit_event(
        self,
        engagement_id: str,
        domain: str,
        event_type: str,
        current_rps: float,
        status_code: Optional[int] = None,
        message: Optional[str] = None
    ) -> None:
        """
        Publish a rate limit event.
        
        Requirements: 31.4
        
        Args:
            engagement_id: Engagement ID
            domain: Target domain
            event_type: Type of rate limit event (throttle, backoff, circuit_breaker)
            current_rps: Current requests per second
            status_code: HTTP status code that triggered the event (if applicable)
            message: Optional message describing the event
        """
        event = {
            "type": self.EVENT_RATE_LIMIT,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "domain": domain,
                "event_type": event_type,
                "status_code": status_code,
                "current_rps": current_rps,
                "message": message or f"Rate limit event: {event_type}",
            }
        }
        self._publish_event(event)
    
    def publish_tool_executed(
        self,
        engagement_id: str,
        tool_name: str,
        duration_ms: int,
        success: bool,
        findings_count: int = 0
    ) -> None:
        """
        Publish a tool execution event.
        
        Args:
            engagement_id: Engagement ID
            tool_name: Name of the tool
            duration_ms: Execution duration in milliseconds
            success: Whether execution was successful
            findings_count: Number of findings discovered
        """
        event = {
            "type": self.EVENT_TOOL_EXECUTED,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "success": success,
                "findings_count": findings_count,
            }
        }
        self._publish_event(event)
    
    def publish_job_started(
        self,
        engagement_id: str,
        job_type: str,
        target: Optional[str] = None
    ) -> None:
        """
        Publish a job started event.
        
        Args:
            engagement_id: Engagement ID
            job_type: Type of job (recon, scan, analyze, report)
            target: Optional target URL
        """
        event = {
            "type": self.EVENT_JOB_STARTED,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "job_type": job_type,
                "target": target,
            }
        }
        self._publish_event(event)
    
    def publish_job_completed(
        self,
        engagement_id: str,
        job_type: str,
        status: str,
        findings_count: int = 0,
        duration_ms: int = 0
    ) -> None:
        """
        Publish a job completed event.
        
        Args:
            engagement_id: Engagement ID
            job_type: Type of job (recon, scan, analyze, report)
            status: Job status (success, failed)
            findings_count: Number of findings discovered
            duration_ms: Total job duration in milliseconds
        """
        event = {
            "type": self.EVENT_JOB_COMPLETED,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "job_type": job_type,
                "status": status,
                "findings_count": findings_count,
                "duration_ms": duration_ms,
            }
        }
        self._publish_event(event)

    def publish_scanner_activity(
        self,
        engagement_id: str,
        tool_name: str,
        activity: str,
        status: str = "in_progress",
        target: str = None,
        details: str = None,
        items_found: int = None,
        duration_ms: int = None
    ) -> None:
        """
        Publish a scanner activity event for live visibility into what tools are doing.
        Also persists the activity to the database for historical review.

        Args:
            engagement_id: Engagement ID
            tool_name: Name of the scanning tool (e.g. 'amass', 'naabu', 'nuclei')
            activity: Human-readable description of the activity
            status: Activity status ('started', 'in_progress', 'completed', 'failed')
            target: Optional target being scanned
            details: Optional additional details / raw output snippet
            items_found: Number of items discovered (subdomains, ports, endpoints, etc.)
            duration_ms: Execution duration in milliseconds
        """
        event = {
            "type": self.EVENT_SCANNER_ACTIVITY,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "tool_name": tool_name,
                "activity": activity,
                "status": status,
                "target": target,
                "details": details,
                "items_found": items_found,
                "duration_ms": duration_ms,
            }
        }
        self._publish_event(event)

        # Persist to database for historical access
        self._persist_scanner_activity(
            engagement_id=engagement_id,
            tool_name=tool_name,
            activity=activity,
            status=status,
            target=target,
            details=details,
            items_found=items_found,
            duration_ms=duration_ms,
        )

    def publish_agent_decision(
        self,
        engagement_id: str,
        iteration: int,
        tool: str,
        reasoning: str,
        was_fallback: bool,
    ) -> None:
        """
        Publish an agent decision event for real-time frontend display.

        Args:
            engagement_id: Engagement ID
            iteration: Iteration number
            tool: Selected tool name
            reasoning: LLM's reasoning
            was_fallback: Whether deterministic fallback was used
        """
        event = {
            "type": self.EVENT_AGENT_DECISION,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "iteration": iteration,
                "tool": tool,
                "reasoning": reasoning[:200] if reasoning else "",
                "was_fallback": was_fallback,
            }
        }
        self._publish_event(event)

    def _persist_scanner_activity(
        self,
        engagement_id: str,
        tool_name: str,
        activity: str,
        status: str,
        target: str = None,
        details: str = None,
        items_found: int = None,
        duration_ms: int = None,
    ) -> None:
        """Write scanner activity to Postgres for persistence."""
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            return
        try:
            from database.connection import connect
            conn = connect(db_url)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scanner_activities
                    (engagement_id, tool_name, activity, status, target, details, items_found, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (engagement_id, tool_name, activity, status, target, details, items_found, duration_ms),
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            # Non-critical: don't let DB write failure break the scan
            import logging
            logging.getLogger(__name__).warning(f"Failed to persist scanner activity: {e}")
    
    def publish_error(
        self,
        engagement_id: str,
        error_message: str,
        error_code: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish an error event.
        
        Args:
            engagement_id: Engagement ID
            error_message: Error message
            error_code: Error code
            context: Additional context
        """
        event = {
            "type": self.EVENT_ERROR,
            "engagement_id": engagement_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "error_message": error_message,
                "error_code": error_code,
                "context": context or {},
            }
        }
        self._publish_event(event)


# Singleton instance
_publisher: Optional[WebSocketEventPublisher] = None


def get_websocket_publisher() -> WebSocketEventPublisher:
    """Get the singleton WebSocket event publisher"""
    global _publisher
    if _publisher is None:
        _publisher = WebSocketEventPublisher()
    return _publisher


# Convenience functions
def publish_finding(
    engagement_id: str,
    finding_id: str,
    finding_type: str,
    severity: str,
    confidence: float,
    endpoint: str,
    source_tool: str
) -> None:
    """Publish a finding discovered event"""
    get_websocket_publisher().publish_finding(
        engagement_id=engagement_id,
        finding_id=finding_id,
        finding_type=finding_type,
        severity=severity,
        confidence=confidence,
        endpoint=endpoint,
        source_tool=source_tool,
    )


def publish_state_transition(
    engagement_id: str,
    from_state: str,
    to_state: str,
    reason: Optional[str] = None
) -> None:
    """Publish a state transition event"""
    get_websocket_publisher().publish_state_transition(
        engagement_id=engagement_id,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
    )


def publish_rate_limit_event(
    engagement_id: str,
    domain: str,
    event_type: str,
    current_rps: float,
    status_code: Optional[int] = None,
    message: Optional[str] = None
) -> None:
    """Publish a rate limit event"""
    get_websocket_publisher().publish_rate_limit_event(
        engagement_id=engagement_id,
        domain=domain,
        event_type=event_type,
        current_rps=current_rps,
        status_code=status_code,
        message=message,
    )
