"""
Transactional Event Streaming — Enforces persist -> commit -> emit ordering.

Implements Section 6 of the Agent Runtime Refactor spec:

    The system MUST follow: persist -> commit -> emit
    NOT: emit -> persist

This module provides a SafeEventEmitter that wraps the existing streaming
emit functions with ordering enforcement. Events are queued and only
emitted after a successful flush (called after DB commit).

Usage:
    from runtime.event_stream import SafeEventEmitter, transactional_event_context

    with transactional_event_context("eng-1") as emitter:
        # 1. Persist data (emit calls are queued automatically)
        save_to_db(result)
        # 2. Commit (db cursor context manager)
        # 3. Flush on exit — events emitted AFTER persistence is confirmed
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class SafeEventEmitter:
    """
    Event emitter that enforces persist -> commit -> emit ordering.

    Events are queued in memory and only flushed to the streaming layer
    when flush() is explicitly called (after DB commit succeeds).

    If flush() is never called (e.g., DB commit failed), queued events
    are silently discarded — preventing phantom findings in the UI.
    """

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self._queue: list[dict] = []
        self._committed = False

    def mark_committed(self):
        """Mark that the DB commit has succeeded for this transaction.

        When called, events will be flushed even if an exception occurs
        after the commit point, preventing phantom data with no event trail.
        """
        self._committed = True

    def emit_thinking(self, message: str, details: dict | None = None):
        """Queue a thinking event."""
        self._queue.append(
            {
                "type": "thinking",
                "engagement_id": self.engagement_id,
                "data": {"message": message, "details": details or {}},
            }
        )

    def emit_tool_start(self, tool: str, args: list[str] | None = None):
        """Queue a tool_start event."""
        self._queue.append(
            {
                "type": "tool_start",
                "engagement_id": self.engagement_id,
                "data": {"tool": tool, "args": args or []},
            }
        )

    def emit_tool_complete(
        self,
        tool: str,
        success: bool,
        duration_ms: int = 0,
        finding_count: int = 0,
    ):
        """Queue a tool_complete event."""
        self._queue.append(
            {
                "type": "tool_complete",
                "engagement_id": self.engagement_id,
                "data": {
                    "tool": tool,
                    "success": success,
                    "duration_ms": duration_ms,
                    "finding_count": finding_count,
                },
            }
        )

    def emit_finding(
        self,
        finding_id: str,
        finding_type: str,
        severity: str,
        confidence: float,
        endpoint: str,
        source_tool: str,
    ):
        """Queue a finding event (matches WebSocketEventPublisher.publish_finding signature)."""
        self._queue.append(
            {
                "type": "finding",
                "engagement_id": self.engagement_id,
                "data": {
                    "finding_id": finding_id,
                    "finding_type": finding_type,
                    "severity": severity,
                    "confidence": confidence,
                    "endpoint": endpoint,
                    "source_tool": source_tool,
                },
            }
        )

    def emit_state_change(self, from_state: str, to_state: str, reason: str = ""):
        """Queue a state_change event (matches WebSocketEventPublisher.publish_state_transition)."""
        self._queue.append(
            {
                "type": "state_change",
                "engagement_id": self.engagement_id,
                "data": {
                    "from_state": from_state,
                    "to_state": to_state,
                    "reason": reason,
                },
            }
        )

    def emit_agent_decision(
        self,
        iteration: int,
        tool: str,
        reasoning: str = "",
        was_fallback: bool = False,
    ):
        """Queue an agent_decision event."""
        self._queue.append(
            {
                "type": "agent_decision",
                "engagement_id": self.engagement_id,
                "data": {
                    "iteration": iteration,
                    "tool": tool,
                    "reasoning": reasoning,
                    "was_fallback": was_fallback,
                },
            }
        )

    def flush(self):
        """
        Flush all queued events to the streaming layer.

        Must be called AFTER the DB commit completes. If the DB commit
        fails, simply discard the queue — no events are emitted.
        """
        if not self._queue:
            return

        try:
            from streaming import (
                emit_agent_decision as _emit_agent_decision,
            )
            from streaming import (
                emit_thinking as _emit_thinking,
            )
            from streaming import (
                emit_tool_complete as _emit_tool_complete,
            )
            from streaming import (
                emit_tool_start as _emit_tool_start,
            )
            from streaming import (
                emit_event as _emit_event,
                emit_state_change as _emit_state_change,
                EventType as _EventType,
            )

            for event in self._queue:
                etype = event["type"]
                data = event["data"]
                try:
                    if etype == "thinking":
                        _emit_thinking(
                            self.engagement_id,
                            data["message"],
                            data.get("details"),
                        )
                    elif etype == "tool_start":
                        _emit_tool_start(
                            self.engagement_id, data["tool"], data.get("args")
                        )
                    elif etype == "tool_complete":
                        _emit_tool_complete(
                            self.engagement_id,
                            data["tool"],
                            data["success"],
                            data.get("duration_ms", 0),
                            data.get("finding_count", 0),
                        )
                    elif etype == "finding":
                        # Gap 10.1: Use SSE emit_event instead of WebSocket
                        _emit_event(
                            self.engagement_id,
                            _EventType.FINDING,
                            {
                                "finding_id": data["finding_id"],
                                "type": data["finding_type"],
                                "severity": data["severity"],
                                "confidence": data["confidence"],
                                "endpoint": data["endpoint"],
                                "source_tool": data.get("source_tool", ""),
                                "title": f"{data['finding_type']} on {data['endpoint']}",
                            },
                        )
                    elif etype == "state_change":
                        # Gap 10.1: Use SSE emit_state_change instead of WebSocket
                        _emit_state_change(
                            self.engagement_id,
                            data["from_state"],
                            data["to_state"],
                            data.get("reason", ""),
                        )
                    elif etype == "agent_decision":
                        _emit_agent_decision(
                            self.engagement_id,
                            data["iteration"],
                            data["tool"],
                            data.get("reasoning", ""),
                            data.get("was_fallback", False),
                        )
                except Exception as e:
                    logger.debug("Failed to emit %s event: %s", etype, e)

        except Exception as e:
            logger.warning("Failed to flush events to streaming layer: %s", e)

        self._queue.clear()

    def discard(self):
        """Discard all queued events without emitting.

        Call this when the DB operation fails — prevents phantom events
        in the UI for operations that were never persisted.
        """
        count = len(self._queue)
        if count > 0:
            logger.debug("Discarding %d queued events (DB operation failed)", count)
        self._queue.clear()

    @property
    def queue_size(self) -> int:
        """Number of events currently queued."""
        return len(self._queue)


@contextmanager
def transactional_event_context(engagement_id: str) -> Iterator[SafeEventEmitter]:
    """Context manager that enforces persist -> commit -> emit ordering.

    All emit_* calls within this context are queued in a SafeEventEmitter
    instead of being published directly. On exit, the queued events are
    flushed to the streaming layer.

    Usage:
        with transactional_event_context("eng-1") as emitter:
            emitter.emit_thinking("Processing...")  # queued
            save_to_db(result)                       # persist
            # DB commit happens (e.g., cursor __exit__)
            # emitter.flush() called automatically on context exit
    """
    from streaming import clear_transactional_emitter, set_transactional_emitter

    emitter = SafeEventEmitter(engagement_id)
    set_transactional_emitter(emitter)
    try:
        yield emitter
    except Exception:
        if emitter._committed:
            emitter.flush()
        else:
            emitter.discard()
        raise
    else:
        emitter.flush()
    finally:
        clear_transactional_emitter()
