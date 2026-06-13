"""
SSE Streaming System and EventBus - Real-time event publishing.

Provides a unified EventBus interface with in-process and Redis adapters,
replacing the dual system of StreamManager + WebSocketEventPublisher.

Callers should use the emit_* convenience functions (emit_thinking,
emit_tool_start, etc.) which delegate to the configured EventBus.

Transactional Event Stream (Step 9):
    When TRANSACTIONAL_EVENTS is enabled, callers should wrap emit calls
    in a transactional context to enforce persist -> commit -> emit ordering.
    Use get_transactional_emitter() to obtain a SafeEventEmitter, then
    call flush_transactional_events() after DB commit.
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

from utils.error_hints import ErrorHint

logger = logging.getLogger(__name__)

# ── Transactional event stream support ──

_transactional_emitter: threading.local = threading.local()
"""Thread-local storage for an optional SafeEventEmitter.
When set, all emit_* functions delegate to this emitter instead of
publishing directly, enabling persist -> commit -> emit ordering."""


def set_transactional_emitter(emitter: Any | None) -> None:
    """Set the thread-local transactional emitter for the current context.

    When set, all emit_* calls will queue events via this emitter instead
    of publishing them directly to the stream manager.

    Args:
        emitter: A SafeEventEmitter instance or None to clear.
    """
    _transactional_emitter.value = emitter


def get_transactional_emitter() -> Any | None:
    """Get the current thread-local transactional emitter, or None."""
    return getattr(_transactional_emitter, "value", None)


def clear_transactional_emitter() -> None:
    """Clear the thread-local transactional emitter."""
    _transactional_emitter.value = None


def flush_transactional_events() -> None:
    """Flush all queued events from the current transactional emitter.

    Must be called AFTER the DB commit completes. If no transactional
    emitter is active, this is a no-op.
    """
    emitter = get_transactional_emitter()
    if emitter is not None:
        emitter.flush()


# ── End of transactional event stream support ──


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
    ERROR_HINT = "error_hint"
    COMPLETE = "complete"
    REPORT_CHUNK = "report_chunk"
    REPORT_COMPLETE = "report_complete"
    AGENT_DECISION = "agent_decision"
    SWARM_AGENT_STARTED = "swarm_agent_started"
    SWARM_AGENT_ACTION = "swarm_agent_action"
    SWARM_AGENT_COMPLETE = "swarm_agent_complete"
    SWARM_MERGE_COMPLETE = "swarm_merge_complete"
    POSTURE_UPDATE = "posture_update"


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
        self._queues: dict[str, list[queue.Queue]] = {}
        self._history: dict[str, list[Event]] = {}
        self._dropped_count: dict[str, int] = {}
        # Periodic eviction counter — triggers stale cleanup every 500
        # publishes to prevent unbounded history growth (M2).
        self._publish_count = 0
        self._eviction_interval = 500

    def subscribe(self, engagement_id: str) -> queue.Queue:
        q = queue.Queue(maxsize=1000)
        with self._lock:
            if engagement_id not in self._queues:
                self._queues[engagement_id] = []
                self._history[engagement_id] = []
                self._dropped_count[engagement_id] = 0
            self._queues[engagement_id].append(q)
        return q

    def unsubscribe(self, engagement_id: str, q: queue.Queue):
        with self._lock:
            if engagement_id in self._queues:
                queues = self._queues[engagement_id]
                # Use a copy for iteration safety — publish() also iterates
                # _queues[engagement_id] under the same lock, so this is safe
                # as long as both methods hold the lock. (C4)
                if q in queues:
                    queues.remove(q)

    def publish(self, event: Event | StreamEvent) -> None:
        """Publish an event to all subscribers.
        Non-blocking — drops events for slow consumers (backpressure).
        Accepts both Event and legacy StreamEvent objects."""
        if isinstance(event, StreamEvent):
            event = Event(
                type=event.event_type.value,
                engagement_id=event.engagement_id,
                data=event.data,
                timestamp=event.timestamp,
            )
        with self._lock:
            engagement_id = event.engagement_id
            if not engagement_id:
                return

            # Store in history (keep last 500)
            if engagement_id in self._history:
                self._history[engagement_id].append(event)
                if len(self._history[engagement_id]) > 500:
                    self._history[engagement_id] = self._history[engagement_id][-500:]

            # Periodic stale engagement eviction (M2)
            self._publish_count += 1
            if self._publish_count % self._eviction_interval == 0:
                self._evict_stale_engagements_inline()

            # Publish to all subscriber queues
            if engagement_id in self._queues:
                dead_queues = []
                for q in self._queues[engagement_id]:
                    try:
                        q.put_nowait(event)
                    except queue.Full:
                        self._dropped_count[engagement_id] = self._dropped_count.get(engagement_id, 0) + 1
                        dropped = self._dropped_count[engagement_id]
                        if dropped <= 5 or dropped % 100 == 0:
                            logger.warning(
                                "StreamManager: queue full for engagement %s, "
                                "dropping event (%d dropped total)",
                                engagement_id, dropped,
                            )
                        dead_queues.append(q)

                for q in dead_queues:
                    with contextlib.suppress(ValueError):
                        self._queues[engagement_id].remove(q)

    def publish_event(self, event: Event):
        self.publish(event)

    def get_history(self, engagement_id: str, since: str = None) -> list[dict]:
        with self._lock:
            events = self._history.get(engagement_id, [])
            if since:
                events = [e for e in events if e.timestamp > since]
            return [e.to_dict() for e in events]

    def clear_engagement(self, engagement_id: str):
        with self._lock:
            self._queues.pop(engagement_id, None)
            self._history.pop(engagement_id, None)
            self._dropped_count.pop(engagement_id, None)

    def get_dropped_count(self, engagement_id: str) -> int:
        with self._lock:
            return self._dropped_count.get(engagement_id, 0)

    def evict_stale_engagements(self, max_engagement_age_seconds: int = 86400):
        """Evict history for engagements older than the given age."""
        with self._lock:
            self._evict_stale_engagements_inline(max_engagement_age_seconds)

    def _evict_stale_engagements_inline(self, max_engagement_age_seconds: int = 86400):
        """Evict stale engagements (must hold self._lock)."""
        cutoff = datetime.now(UTC).timestamp() - max_engagement_age_seconds
        stale = []
        for eid, events in self._history.items():
            if events and events[-1].timestamp:
                try:
                    ts = datetime.fromisoformat(events[-1].timestamp).timestamp()
                    if ts < cutoff:
                        stale.append(eid)
                except (ValueError, OSError):
                    pass
        for eid in stale:
            self._queues.pop(eid, None)
            self._history.pop(eid, None)
            self._dropped_count.pop(eid, None)
        if stale:
            logger.debug("Evicted %d stale engagement histories", len(stale))


# Convenience functions for publishing common events

def _maybe_transactional(engagement_id: str, event_type: str, data: dict) -> bool:
    """If a transactional emitter is active, delegate to it.

    Returns True if the event was handled transactionally (queued),
    False if the caller should publish directly.
    """
    emitter = get_transactional_emitter()
    if emitter is None:
        return False
    try:
        if event_type == "thinking":
            emitter.emit_thinking(data.get("message", ""), data.get("details"))
        elif event_type == "tool_start":
            emitter.emit_tool_start(data["tool"], data.get("args"))
        elif event_type == "tool_complete":
            emitter.emit_tool_complete(
                data["tool"], data["success"],
                data.get("duration_ms", 0), data.get("findings", 0),
            )
        elif event_type == "finding":
            emitter.emit_finding(
                data.get("_id", ""), data.get("type", ""), data.get("severity", "INFO"),
                data.get("confidence", 0.5), data.get("endpoint", ""),
                data.get("source_tool", ""),
            )
        elif event_type == "state_change":
            emitter.emit_state_change(
                data.get("from", ""), data.get("to", ""),
                data.get("reason", ""),
            )
    except Exception:
        logger.debug("Transactional emitter delegate failed for %s", event_type, exc_info=True)
        return False
    return True


def emit_thinking(engagement_id: str, message: str, details: dict = None):
    """Emit a thinking/reasoning event."""
    data = {"message": message, "details": details or {}}
    if _maybe_transactional(engagement_id, "thinking", data):
        return
    get_stream_manager().publish(Event(
        type=EventType.THINKING,
        engagement_id=engagement_id,
        data={"message": message, **(details or {})},
    ))


def emit_tool_start(engagement_id: str, tool: str, args: list[str] = None):
    """Emit a tool execution start event."""
    data = {"tool": tool, "args": args or []}
    if _maybe_transactional(engagement_id, "tool_start", data):
        return
    get_stream_manager().publish(Event(
        type=EventType.TOOL_START,
        engagement_id=engagement_id,
        data={"tool": tool, "args": args or []},
    ))


def emit_tool_output(engagement_id: str, tool: str, output: str, is_stderr: bool = False):
    """Emit a tool output chunk event."""
    get_stream_manager().publish(Event(
        type=EventType.TOOL_OUTPUT,
        engagement_id=engagement_id,
        data={"tool": tool, "output": output, "is_stderr": is_stderr},
    ))


def emit_tool_complete(engagement_id: str, tool: str, success: bool, duration_ms: int, finding_count: int = 0):
    """Emit a tool execution complete event."""
    data = {
        "tool": tool, "success": success,
        "duration_ms": duration_ms, "findings": finding_count,
    }
    if _maybe_transactional(engagement_id, "tool_complete", data):
        return
    get_stream_manager().publish(Event(
        type=EventType.TOOL_COMPLETE,
        engagement_id=engagement_id,
        data={
            "tool": tool,
            "success": success,
            "duration_ms": duration_ms,
            "findings": finding_count,
        },
    ))


def emit_finding(
    engagement_id: str, finding_type: str, severity: str, endpoint: str, title: str,
    confidence: float | None = None, source_tool: str | None = None,
):
    """Emit a finding discovered event.

    Args:
        engagement_id: Engagement UUID
        finding_type: Type of finding (XSS, SQL_INJECTION, etc.)
        severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW, INFO)
        endpoint: Affected endpoint URL
        title: Human-readable title
        confidence: Optional confidence score 0.0-1.0
        source_tool: Optional tool that discovered the finding
    """
    data = {"type": finding_type, "severity": severity, "endpoint": endpoint, "title": title}
    if confidence is not None:
        data["confidence"] = confidence
    if source_tool is not None:
        data["source_tool"] = source_tool
    if _maybe_transactional(engagement_id, "finding", data):
        return
    event_data = {
        "type": finding_type,
        "severity": severity,
        "endpoint": endpoint,
        "title": title,
    }
    if confidence is not None:
        event_data["confidence"] = confidence
    if source_tool is not None:
        event_data["source_tool"] = source_tool
    get_stream_manager().publish(Event(
        type=EventType.FINDING,
        engagement_id=engagement_id,
        data=event_data,
    ))


def emit_state_change(engagement_id: str, from_state: str, to_state: str, reason: str = ""):
    """Emit a state transition event."""
    data = {"from": from_state, "to": to_state, "reason": reason}
    if _maybe_transactional(engagement_id, "state_change", data):
        return
    get_stream_manager().publish(Event(
        type=EventType.STATE_CHANGE,
        engagement_id=engagement_id,
        data={
            "from": from_state,
            "to": to_state,
            "reason": reason,
        },
    ))


def emit_progress(engagement_id: str, phase: str, progress: float, message: str = ""):
    """Emit a progress update (0.0 to 1.0)."""
    get_stream_manager().publish(Event(
        type=EventType.PROGRESS,
        engagement_id=engagement_id,
        data={
            "phase": phase,
            "progress": progress,
            "message": message,
        },
    ))


def emit_error(engagement_id: str, error: str, phase: str = ""):
    """Emit an error event."""
    get_stream_manager().publish(Event(
        type=EventType.ERROR,
        engagement_id=engagement_id,
        data={"error": error, "phase": phase},
    ))


def emit_error_hint(
    engagement_id: str,
    hint: ErrorHint,
) -> None:
    """Emit a user-facing error hint to the UI.

    ERROR_HINT is a separate event type from ERROR — they are independently
    consumable by consumers (e.g., TUI can render hints differently from errors).

    Args:
        engagement_id: Engagement UUID.
        hint: ErrorHint object with summary, detail, remediation, etc.
    """
    get_stream_manager().publish(Event(
        type=EventType.ERROR_HINT,
        engagement_id=engagement_id,
        data=hint.to_dict(),
    ))


def emit_complete(engagement_id: str, phase: str, summary: dict = None):
    """Emit a phase complete event."""
    get_stream_manager().publish(Event(
        type=EventType.COMPLETE,
        engagement_id=engagement_id,
        data={"phase": phase, "summary": summary or {}},
    ))


def emit_report_chunk(engagement_id: str, text: str):
    """Emit an incremental report chunk."""
    get_stream_manager().publish(Event(
        type=EventType.REPORT_CHUNK,
        engagement_id=engagement_id,
        data={"text": text},
    ))


def emit_report_complete(engagement_id: str, summary: dict = None):
    """Emit a report complete event."""
    get_stream_manager().publish(Event(
        type=EventType.REPORT_COMPLETE,
        engagement_id=engagement_id,
        data={"summary": summary or {}},
    ))


def emit_agent_decision(
    engagement_id: str,
    iteration: int,
    tool: str,
    reasoning: str,
    was_fallback: bool = False,
    agent_domain: str = "general",
):
    """Emit an agent decision event for the frontend reasoning feed."""
    get_stream_manager().publish(Event(
        type=EventType.THINKING,
        engagement_id=engagement_id,
        data={
            "type": "agent_decision",
            "iteration": iteration,
            "tool": tool,
            "reasoning": reasoning[:200] if reasoning else "",
            "was_fallback": was_fallback,
            "agent_domain": agent_domain,
        },
    ))


def emit_swarm_agent_started(engagement_id: str, domain: str):
    """Emit a swarm agent activation event."""
    get_stream_manager().publish(Event(
        type=EventType.SWARM_AGENT_STARTED,
        engagement_id=engagement_id,
        data={"domain": domain},
    ))


def emit_swarm_agent_action(
    engagement_id: str,
    domain: str,
    tool: str,
    reasoning: str,
    iteration: int = 0,
):
    """Emit a swarm agent tool selection action."""
    get_stream_manager().publish(Event(
        type=EventType.SWARM_AGENT_ACTION,
        engagement_id=engagement_id,
        data={
            "domain": domain,
            "tool": tool,
            "reasoning": reasoning[:200] if reasoning else "",
            "iteration": iteration,
        },
    ))


def emit_swarm_agent_complete(
    engagement_id: str,
    domain: str,
    findings_count: int,
):
    """Emit a swarm agent completion event."""
    get_stream_manager().publish(Event(
        type=EventType.SWARM_AGENT_COMPLETE,
        engagement_id=engagement_id,
        data={
            "domain": domain,
            "findings_count": findings_count,
        },
    ))


def emit_swarm_merge_complete(
    engagement_id: str,
    total_findings: int,
    dedup_removed: int,
):
    """Emit a swarm merge complete event."""
    get_stream_manager().publish(Event(
        type=EventType.SWARM_MERGE_COMPLETE,
        engagement_id=engagement_id,
        data={
            "total_findings": total_findings,
            "dedup_removed": dedup_removed,
        },
    ))


def emit_posture_update(
    engagement_id: str,
    composite_score: float,
    framework_scores: dict[str, float],
    trend: str,
    total_findings: int,
) -> None:
    """Emit a compliance posture update event via SSE and WebSocket."""
    get_stream_manager().publish(Event(
        type=EventType.POSTURE_UPDATE,
        engagement_id=engagement_id,
        data={
            "composite_score": composite_score,
            "framework_scores": framework_scores,
            "trend": trend,
            "total_findings": total_findings,
        },
    ))
    # Note: WebSocket publishing removed (M-07 consolidation).


# ── StreamingFindingEmitter: unified finding stream ──

class StreamingFindingEmitter:
    """
    Unified emitter that publishes finding events via SSE (in-process stream manager).

    Every normalized finding that gets persisted to the database also gets emitted
    as a real-time event so analysts can start triaging critical findings while the
    scan is still running.

    Uses lazy initialization for stream manager to avoid import-time side effects.

    All events go through SSE only (M-07 consolidation). The frontend consumes
    events via the SSE endpoint at /api/stream/[id].
    """

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self._stream = None

    @property
    def stream(self):
        if self._stream is None:
            self._stream = get_stream_manager()
        return self._stream

    def emit_finding(self, finding: dict) -> None:
        """Emit a finding event via SSE.

        Args:
            finding: Finding dict containing at minimum:
                - _saved_id or id: Finding UUID
                - type: Finding type (SQL_INJECTION, XSS, etc.)
                - severity: CRITICAL, HIGH, MEDIUM, LOW, INFO
                - endpoint: Affected endpoint
                - source_tool: Tool that discovered the finding
                - confidence: Confidence score 0.0-1.0
        """
        finding_type = finding.get("type", "UNKNOWN")
        severity = finding.get("severity", "INFO")
        endpoint = finding.get("endpoint", "")
        title = f"{finding_type} on {endpoint}"

        # SSE event via emit_finding (in-process stream manager)
        emit_finding(self.engagement_id, finding_type, severity, endpoint, title)

        # Note: WebSocket publishing removed (M-07 consolidation).
        # All events go through SSE only.


# In-memory dedup for emit_finding_rt to prevent duplicate findings
# from being emitted via SSE/WebSocket. Keyed by engagement_id so sets
# are naturally scoped to a single scan and don't grow unbounded.
_rt_emitted_fingerprints: dict[str, set[str]] = {}
_rt_fingerprints_lock = threading.Lock()


def _rt_fingerprint(finding_type: str, endpoint: str, source_tool: str = "") -> str:
    """Build a dedup key from type, endpoint, and source_tool.

    Including source_tool prevents collisions where two different scanners
    (e.g. web_scanner and nuclei) report the same type+endpoint for
    genuinely distinct root causes.
    """
    return f"{finding_type}|{endpoint}|{source_tool}"


def clear_engagement_rt_fingerprints(engagement_id: str) -> None:
    """Remove stored fingerprints for a completed engagement.

    Prevents unbounded memory growth in _rt_emitted_fingerprints across
    multiple scan engagements. Safe to call multiple times.
    """
    with _rt_fingerprints_lock:
        _rt_emitted_fingerprints.pop(engagement_id, None)


def emit_finding_rt(
    engagement_id: str,
    finding: dict,
    tool_name: str,
) -> None:
    """Emit a finding in real-time via SSE and WebSocket as it's discovered.

    This is called immediately after a finding is parsed and normalized,
    before it's saved to the database. It gives analysts visibility into
    findings as they're discovered rather than waiting for the batch save.

    Dual-channel emission:
      1. SSE (in-process stream manager) — used by the engagement detail page
      2. WebSocket (Redis pub/sub) — used by the findings list and monitoring pages

    This is intentionally non-fatal: if emission fails, the scan continues.

    In-flight dedup: uses a module-level fingerprint set keyed by type|endpoint
    so the same finding is never emitted more than once per process lifetime.
    """
    if not engagement_id:
        return

    finding_type = finding.get("type", "UNKNOWN")
    severity = finding.get("severity", "INFO")
    endpoint = finding.get("endpoint", "")
    source_tool = finding.get("source_tool", tool_name)
    confidence = finding.get("confidence", 0.5)
    # In-flight dedup: skip if we've already emitted this type+endpoint+tool combo
    fp = _rt_fingerprint(finding_type, endpoint, source_tool)
    with _rt_fingerprints_lock:
        engagement_fps = _rt_emitted_fingerprints.setdefault(engagement_id, set())
        if fp in engagement_fps:
            logger.log(5, "Dedup emit_finding_rt: %s", fp)
            return
        engagement_fps.add(fp)

    # 1. SSE emission (in-process stream manager)
    try:
        emit_finding(
            engagement_id=engagement_id,
            finding_type=finding_type,
            severity=severity,
            endpoint=endpoint,
            title=f"{finding_type} on {endpoint}",
            confidence=confidence,
            source_tool=source_tool,
        )
    except Exception as e:
        logger.debug("SSE finding emit failed (non-fatal): %s", e)

    # WebSocket emission removed (M-07 consolidation).
    # All events go through SSE only.


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
