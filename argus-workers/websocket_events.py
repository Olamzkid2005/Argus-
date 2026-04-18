"""
WebSocket Events Publisher

Publishes real-time events to Redis for WebSocket distribution.
Used by Python workers to notify the frontend of findings, state changes,
and other engagement updates.

Requirements: 31.2, 31.3, 31.4
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import redis


class WebSocketEventPublisher:
    """
    Publishes events to Redis for WebSocket distribution.
    
    Events are stored in Redis lists for polling and published
    to Redis channels for active subscribers.
    """
    
    # Event types
    EVENT_FINDING_DISCOVERED = "finding_discovered"
    EVENT_STATE_TRANSITION = "state_transition"
    EVENT_RATE_LIMIT = "rate_limit_event"
    EVENT_TOOL_EXECUTED = "tool_executed"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_COMPLETED = "job_completed"
    EVENT_ERROR = "error"
    
    # Redis configuration
    EVENTS_TTL = 300  # 5 minutes
    MAX_EVENTS = 100
    
    def __init__(self, redis_url: str = None):
        """
        Initialize the WebSocket event publisher.
        
        Args:
            redis_url: Redis connection URL (defaults to REDIS_URL env var)
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._redis = None
    
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
    
    def _publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish an event to Redis.
        
        Args:
            event: Event dictionary with type, engagement_id, timestamp, and data
        """
        engagement_id = event.get("engagement_id")
        if not engagement_id:
            raise ValueError("Event must have engagement_id")
        
        # Store in Redis list for polling
        events_key = self._get_events_key(engagement_id)
        self.redis.lpush(events_key, json.dumps(event))
        self.redis.ltrim(events_key, 0, self.MAX_EVENTS - 1)
        self.redis.expire(events_key, self.EVENTS_TTL)
        
        # Publish to channel for active subscribers
        channel = self._get_channel(engagement_id)
        self.redis.publish(channel, json.dumps(event))
    
    def publish_finding(
        self,
        engagement_id: str,
        finding_id: str,
        finding_type: str,
        severity: str,
        confidence: float,
        endpoint: str,
        source_tool: str
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
