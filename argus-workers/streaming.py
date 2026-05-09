"""
SSE Streaming System and EventBus - Real-time event publishing.

Provides a unified EventBus interface with in-process and Redis adapters,
replacing the dual system of StreamManager + WebSocketEventPublisher.

Callers should use the emit_* convenience functions (emit_thinking,
emit_tool_start, etc.) which delegate to the configured EventBus.
"""
import contextlib
import json
import logging
import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Unified Event schema ──

@dataclass
class Event:
    """Single event with unified field names for both SSE and Redis consumers."""
    type: str
    engagement_id: str
    data: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.to_dict())}\n\n"

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "engagement_id": self.engagement_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# ── Event types (single source) ──

class EventType:
    """Unified event type constants."""
    THINKING = "thinking"
    TOOL_OUTPUT = "tool_output"
    TOOL_START = "tool_start"
    TOOL_COMPLETE = "tool_complete"
    FINDING = "finding"
    STATE_CHANGE = "state_change"
    PROGRESS = "progress"
    ERROR = "error"
    COMPLETE = "complete"
    REPORT_CHUNK = "report_chunk"
    REPORT_COMPLETE = "report_complete"
    AGENT_DECISION = "agent_decision"
    SWARM_AGENT_STARTED = "swarm_agent_started"
    SWARM_AGENT_ACTION = "swarm_agent_action"
    SWARM_AGENT_COMPLETE = "swarm_agent_complete"
    SWARM_MERGE_COMPLETE = "swarm_merge_complete"


# ── EventBus Port (ABC) ──

class EventBus(ABC):
    """Port: the single interface all event producers use."""

    @abstractmethod
    def publish(self, event: Event) -> None:
        ...

    @abstractmethod
    def subscribe(self, engagement_id: str) -> queue.Queue:
        ...

    @abstractmethod
    def get_history(self, engagement_id: str, since: str = None) -> list[dict]:
        ...


# ── Backward-compatible StreamEventType and StreamEvent ──

class StreamEventType(Enum):
    """Types of SSE events (legacy, use EventType for new code)."""
    THINKING = EventType.THINKING
    TOOL_OUTPUT = EventType.TOOL_OUTPUT
    TOOL_START = EventType.TOOL_START
    TOOL_COMPLETE = EventType.TOOL_COMPLETE
    FINDING = EventType.FINDING
    STATE_CHANGE = EventType.STATE_CHANGE
    PROGRESS = EventType.PROGRESS
    ERROR = EventType.ERROR
    COMPLETE = EventType.COMPLETE
    REPORT_CHUNK = EventType.REPORT_CHUNK
    REPORT_COMPLETE = EventType.REPORT_COMPLETE
    SWARM_AGENT_STARTED = EventType.SWARM_AGENT_STARTED
    SWARM_AGENT_ACTION = EventType.SWARM_AGENT_ACTION
    SWARM_AGENT_COMPLETE = EventType.SWARM_AGENT_COMPLETE
    SWARM_MERGE_COMPLETE = EventType.SWARM_MERGE_COMPLETE


@dataclass
class StreamEvent:
    """A single SSE event (legacy, use Event for new code)."""
    event_type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    engagement_id: str = ""

    def to_sse(self) -> str:
        """Format as SSE protocol message."""
        payload = {
            "type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }
        if self.engagement_id:
            payload["engagement_id"] = self.engagement_id
        return f"data: {json.dumps(payload)}\n\n"

    def to_dict(self) -> dict:
        return {
            "type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "engagement_id": self.engagement_id,
        }


class StreamManager(EventBus):
    """
    Manages SSE event streams for multiple engagements (in-process).

    Implements EventBus port. Supports multiple subscribers per engagement,
    event queuing with backpressure, and thread-safe publish/subscribe.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._queues: dict[str, list[queue.Queue]] = {}  # engagement_id -> [queues]
        self._history: dict[str, list[StreamEvent]] = {}  # engagement_id -> last N events

    def subscribe(self, engagement_id: str) -> queue.Queue:
        """
        Subscribe to events for an engagement.
        Returns a queue that the subscriber can poll.
        """
        q = queue.Queue(maxsize=1000)  # Backpressure limit
        with self._lock:
            if engagement_id not in self._queues:
                self._queues[engagement_id] = []
                self._history[engagement_id] = []
            self._queues[engagement_id].append(q)
        return q

    def unsubscribe(self, engagement_id: str, q: queue.Queue):
        """Remove a subscriber queue."""
        with self._lock:
            if engagement_id in self._queues:
                with contextlib.suppress(ValueError):
                    self._queues[engagement_id].remove(q)

    def publish(self, event: StreamEvent):
        """
        Publish an event to all subscribers of the engagement.
        Non-blocking - drops events for slow consumers (backpressure).
        """
        with self._lock:
            engagement_id = event.engagement_id
            if not engagement_id:
                return

            # Store in history (keep last 500)
            if engagement_id in self._history:
                self._history[engagement_id].append(event)
                if len(self._history[engagement_id]) > 500:
                    self._history[engagement_id] = self._history[engagement_id][-500:]

            # Publish to all subscriber queues
            if engagement_id in self._queues:
                dead_queues = []
                for q in self._queues[engagement_id]:
                    try:
                        q.put_nowait(event)
                    except queue.Full:
                        dead_queues.append(q)

                for q in dead_queues:
                    with contextlib.suppress(ValueError):
                        self._queues[engagement_id].remove(q)

    def publish_event(self, event: Event):
        """Publish a new-format Event (wraps to StreamEvent for backward compat)."""
        stream_event = StreamEvent(
            event_type=StreamEventType(event.type),
            data=event.data,
            engagement_id=event.engagement_id,
            timestamp=event.timestamp,
        )
        self.publish(stream_event)

    def get_history(self, engagement_id: str, since: str = None) -> list[dict]:
        """Get event history for an engagement, optionally since a timestamp."""
        with self._lock:
            events = self._history.get(engagement_id, [])
            if since:
                events = [e for e in events if e.timestamp > since]
            return [e.to_dict() for e in events]

    def clear_engagement(self, engagement_id: str):
        """Clear all subscribers and history for an engagement."""
        with self._lock:
            self._queues.pop(engagement_id, None)
            self._history.pop(engagement_id, None)


# Convenience functions for publishing common events

def emit_thinking(engagement_id: str, message: str, details: dict = None):
    """Emit a thinking/reasoning event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.THINKING,
        data={"message": message, **(details or {})},
        engagement_id=engagement_id,
    ))


def emit_tool_start(engagement_id: str, tool: str, args: list[str] = None):
    """Emit a tool execution start event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.TOOL_START,
        data={"tool": tool, "args": args or []},
        engagement_id=engagement_id,
    ))


def emit_tool_output(engagement_id: str, tool: str, output: str, is_stderr: bool = False):
    """Emit a tool output chunk event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.TOOL_OUTPUT,
        data={"tool": tool, "output": output, "is_stderr": is_stderr},
        engagement_id=engagement_id,
    ))


def emit_tool_complete(engagement_id: str, tool: str, success: bool, duration_ms: int, finding_count: int = 0):
    """Emit a tool execution complete event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.TOOL_COMPLETE,
        data={
            "tool": tool,
            "success": success,
            "duration_ms": duration_ms,
            "findings": finding_count,
        },
        engagement_id=engagement_id,
    ))


def emit_finding(engagement_id: str, finding_type: str, severity: str, endpoint: str, title: str):
    """Emit a finding discovered event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.FINDING,
        data={
            "type": finding_type,
            "severity": severity,
            "endpoint": endpoint,
            "title": title,
        },
        engagement_id=engagement_id,
    ))


def emit_state_change(engagement_id: str, from_state: str, to_state: str, reason: str = ""):
    """Emit a state transition event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.STATE_CHANGE,
        data={
            "from": from_state,
            "to": to_state,
            "reason": reason,
        },
        engagement_id=engagement_id,
    ))


def emit_progress(engagement_id: str, phase: str, progress: float, message: str = ""):
    """Emit a progress update (0.0 to 1.0)."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.PROGRESS,
        data={
            "phase": phase,
            "progress": progress,
            "message": message,
        },
        engagement_id=engagement_id,
    ))


def emit_error(engagement_id: str, error: str, phase: str = ""):
    """Emit an error event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.ERROR,
        data={"error": error, "phase": phase},
        engagement_id=engagement_id,
    ))


def emit_complete(engagement_id: str, phase: str, summary: dict = None):
    """Emit a phase complete event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.COMPLETE,
        data={"phase": phase, "summary": summary or {}},
        engagement_id=engagement_id,
    ))


def emit_report_chunk(engagement_id: str, text: str):
    """Emit an incremental report chunk."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.REPORT_CHUNK,
        data={"text": text},
        engagement_id=engagement_id,
    ))


def emit_report_complete(engagement_id: str, summary: dict = None):
    """Emit a report complete event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.REPORT_COMPLETE,
        data={"summary": summary or {}},
        engagement_id=engagement_id,
    ))


def emit_agent_decision(
    engagement_id: str,
    iteration: int,
    tool: str,
    reasoning: str,
    was_fallback: bool = False,
    agent_domain: str = "general",
):
    """Emit an agent decision event for the frontend reasoning feed.

    Args:
        engagement_id: Engagement UUID
        iteration: Agent loop iteration
        tool: Selected tool name
        reasoning: LLM reasoning for tool selection
        was_fallback: Whether deterministic fallback was used
        agent_domain: Agent domain (general, idor, auth, api)
    """
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.THINKING,
        data={
            "type": "agent_decision",
            "iteration": iteration,
            "tool": tool,
            "reasoning": reasoning[:200] if reasoning else "",
            "was_fallback": was_fallback,
            "agent_domain": agent_domain,
        },
        engagement_id=engagement_id,
    ))


def emit_swarm_agent_started(engagement_id: str, domain: str):
    """Emit a swarm agent activation event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.SWARM_AGENT_STARTED,
        data={"domain": domain},
        engagement_id=engagement_id,
    ))


def emit_swarm_agent_action(
    engagement_id: str,
    domain: str,
    tool: str,
    reasoning: str,
    iteration: int,
):
    """Emit a swarm agent tool selection action."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.SWARM_AGENT_ACTION,
        data={
            "domain": domain,
            "tool": tool,
            "reasoning": reasoning[:200] if reasoning else "",
            "iteration": iteration,
        },
        engagement_id=engagement_id,
    ))


def emit_swarm_agent_complete(
    engagement_id: str,
    domain: str,
    findings_count: int,
):
    """Emit a swarm agent completion event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.SWARM_AGENT_COMPLETE,
        data={
            "domain": domain,
            "findings_count": findings_count,
        },
        engagement_id=engagement_id,
    ))


def emit_swarm_merge_complete(
    engagement_id: str,
    total_findings: int,
    dedup_removed: int,
):
    """Emit a swarm merge complete event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.SWARM_MERGE_COMPLETE,
        data={
            "total_findings": total_findings,
            "dedup_removed": dedup_removed,
        },
        engagement_id=engagement_id,
    ))


# Singleton
_stream_manager: StreamManager | None = None
_stream_lock = threading.Lock()


def get_stream_manager() -> StreamManager:
    """Get the singleton StreamManager instance."""
    global _stream_manager
    if _stream_manager is None:
        with _stream_lock:
            if _stream_manager is None:
                _stream_manager = StreamManager()
    return _stream_manager
