"""
SSE Streaming System - Real-time tool output streaming

Replaces Celery task push model with SSE (Server-Sent Events) for:
- Thinking deltas ("Running nuclei against target...")
- Tool output chunks (line-by-line results)
- Finding discovered events
- State transitions
- Progress updates

This mirrors CyberStrikeAI's streaming architecture where
the frontend receives real-time updates via SSE endpoints.
"""
import json
import logging
import threading
import time
import queue
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class StreamEventType(Enum):
    """Types of SSE events that can be emitted."""
    THINKING = "thinking"           # "Running nuclei against target..."
    TOOL_OUTPUT = "tool_output"     # Line-by-line tool stdout/stderr
    TOOL_START = "tool_start"       # Tool execution started
    TOOL_COMPLETE = "tool_complete" # Tool execution finished
    FINDING = "finding"             # New finding discovered
    STATE_CHANGE = "state_change"   # Engagement state transition
    PROGRESS = "progress"           # Progress percentage
    ERROR = "error"                 # Error event
    COMPLETE = "complete"           # Scan phase complete
    REPORT_CHUNK = "report_chunk"   # Incremental report text from LLM
    REPORT_COMPLETE = "report_complete"  # Final report ready


@dataclass
class StreamEvent:
    """A single SSE event."""
    event_type: StreamEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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

    def to_dict(self) -> Dict:
        return {
            "type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "engagement_id": self.engagement_id,
        }


class StreamManager:
    """
    Manages SSE event streams for multiple engagements.

    Supports:
    - Multiple subscribers per engagement
    - Event queuing with backpressure
    - Thread-safe publish/subscribe
    - Automatic cleanup of disconnected clients
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._queues: Dict[str, List[queue.Queue]] = {}  # engagement_id -> [queues]
        self._history: Dict[str, List[StreamEvent]] = {}  # engagement_id -> last N events

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
                try:
                    self._queues[engagement_id].remove(q)
                except ValueError:
                    pass

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
                        # Consumer is too slow - drop event
                        dead_queues.append(q)

                # Clean up dead queues
                for q in dead_queues:
                    try:
                        self._queues[engagement_id].remove(q)
                    except ValueError:
                        pass

    def get_history(self, engagement_id: str, since: str = None) -> List[Dict]:
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

def emit_thinking(engagement_id: str, message: str, details: Dict = None):
    """Emit a thinking/reasoning event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.THINKING,
        data={"message": message, **(details or {})},
        engagement_id=engagement_id,
    ))


def emit_tool_start(engagement_id: str, tool: str, args: List[str] = None):
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


def emit_complete(engagement_id: str, phase: str, summary: Dict = None):
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


def emit_report_complete(engagement_id: str, summary: Dict = None):
    """Emit a report complete event."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.REPORT_COMPLETE,
        data={"summary": summary or {}},
        engagement_id=engagement_id,
    ))


def emit_agent_decision(engagement_id: str, iteration: int, tool: str, reasoning: str, was_fallback: bool = False):
    """Emit an agent decision event for the frontend reasoning feed."""
    get_stream_manager().publish(StreamEvent(
        event_type=StreamEventType.THINKING,
        data={
            "type": "agent_decision",
            "iteration": iteration,
            "tool": tool,
            "reasoning": reasoning[:200] if reasoning else "",
            "was_fallback": was_fallback,
        },
        engagement_id=engagement_id,
    ))


# Singleton
_stream_manager: Optional[StreamManager] = None
_stream_lock = threading.Lock()


def get_stream_manager() -> StreamManager:
    """Get the singleton StreamManager instance."""
    global _stream_manager
    if _stream_manager is None:
        with _stream_lock:
            if _stream_manager is None:
                _stream_manager = StreamManager()
    return _stream_manager
