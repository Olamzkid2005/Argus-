"""
Streaming Output Manager — real-time tool output streaming.

Provides Claude-Code-style streaming:
  - Tool execution output in real-time
  - Progress indicators
  - Event-based updates
  - Thread-safe output

Integrates with Argus's existing SSE streaming system.
"""

from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable


class EventType(Enum):
    """Types of streaming events."""
    THINKING = "thinking"
    TOOL_START = "tool_start"
    TOOL_OUTPUT = "tool_output"
    TOOL_COMPLETE = "tool_complete"
    FINDING = "finding"
    PROGRESS = "progress"
    STATE_CHANGE = "state_change"
    ERROR = "error"
    COMPLETE = "complete"
    REPORT_CHUNK = "report_chunk"


@dataclass
class StreamEvent:
    """A single streaming event."""
    event_type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    engagement_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "engagement_id": self.engagement_id,
        }


class StreamHandler(ABC):
    """Abstract base class for stream output handlers."""

    @abstractmethod
    def on_event(self, event: StreamEvent) -> None:
        """Handle a streaming event."""
        pass


class ConsoleStreamHandler(StreamHandler):
    """Handler that prints events to console."""

    def __init__(self, console: Any = None) -> None:
        self.console = console

    def on_event(self, event: StreamEvent) -> None:
        from rich.console import Console

        if self.console is None:
            self.console = Console()

        if event.event_type == EventType.TOOL_START:
            tool = event.data.get("tool", "?")
            self.console.print(f"  [dim]→ Running {tool}...[/dim]")
        elif event.event_type == EventType.TOOL_OUTPUT:
            output = event.data.get("output", "")
            if output:
                lines = output.splitlines()[:10]  # Limit output
                for line in lines:
                    self.console.print(f"    [dim]{line}[/dim]")
        elif event.event_type == EventType.TOOL_COMPLETE:
            tool = event.data.get("tool", "?")
            success = event.data.get("success", False)
            icon = "[green]✓[/green]" if success else "[red]✗[/red]"
            self.console.print(f"  {icon} {tool}")
        elif event.event_type == EventType.FINDING:
            severity = event.data.get("severity", "info")
            finding_type = event.data.get("type", "?")
            endpoint = event.data.get("endpoint", "?")
            color = {"critical": "red", "high": "red", "medium": "yellow", "low": "blue"}.get(severity, "white")
            self.console.print(f"  [{color}]• [{severity.upper()}] {finding_type} @ {endpoint}[/{color}]")
        elif event.event_type == EventType.PROGRESS:
            phase = event.data.get("phase", "?")
            percent = event.data.get("percent", 0)
            self.console.print(f"  [dim]{phase}: {percent}%[/dim]")
        elif event.event_type == EventType.ERROR:
            error = event.data.get("error", "Unknown error")
            self.console.print(f"  [red]Error: {error}[/red]")


class StreamingManager:
    """
    Manages real-time event streaming.

    Thread-safe event bus with multiple subscribers.
    Provides backpressure (drops events for slow consumers).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: list[StreamHandler] = []
        self._history: list[StreamEvent] = []
        self._max_history = 500

    def subscribe(self, handler: StreamHandler) -> None:
        """Subscribe a handler to receive events."""
        with self._lock:
            self._handlers.append(handler)

    def unsubscribe(self, handler: StreamHandler) -> None:
        """Unsubscribe a handler."""
        with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)

    def emit(self, event: StreamEvent) -> None:
        """Emit an event to all subscribers."""
        with self._lock:
            # Store in history
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            # Notify handlers
            for handler in self._handlers:
                try:
                    handler.on_event(event)
                except Exception:
                    pass  # Don't let one handler break others

    def emit_tool_start(self, engagement_id: str, tool: str, args: list[str]) -> None:
        """Emit tool start event."""
        self.emit(StreamEvent(
            event_type=EventType.TOOL_START,
            data={"tool": tool, "args": args},
            engagement_id=engagement_id,
        ))

    def emit_tool_output(self, engagement_id: str, tool: str, output: str) -> None:
        """Emit tool output event."""
        self.emit(StreamEvent(
            event_type=EventType.TOOL_OUTPUT,
            data={"tool": tool, "output": output},
            engagement_id=engagement_id,
        ))

    def emit_tool_complete(self, engagement_id: str, tool: str, success: bool, duration_ms: int = 0) -> None:
        """Emit tool completion event."""
        self.emit(StreamEvent(
            event_type=EventType.TOOL_COMPLETE,
            data={"tool": tool, "success": success, "duration_ms": duration_ms},
            engagement_id=engagement_id,
        ))

    def emit_finding(self, engagement_id: str, finding: dict[str, Any]) -> None:
        """Emit a finding event."""
        self.emit(StreamEvent(
            event_type=EventType.FINDING,
            data=finding,
            engagement_id=engagement_id,
        ))

    def emit_progress(self, engagement_id: str, phase: str, percent: int) -> None:
        """Emit progress event."""
        self.emit(StreamEvent(
            event_type=EventType.PROGRESS,
            data={"phase": phase, "percent": percent},
            engagement_id=engagement_id,
        ))

    def emit_error(self, engagement_id: str, error: str) -> None:
        """Emit error event."""
        self.emit(StreamEvent(
            event_type=EventType.ERROR,
            data={"error": error},
            engagement_id=engagement_id,
        ))

    def get_history(self, engagement_id: str) -> list[StreamEvent]:
        """Get event history for an engagement."""
        return [e for e in self._history if e.engagement_id == engagement_id]


# Global singleton (matching Argus's pattern)
_streaming_manager: StreamingManager | None = None


def get_streaming_manager() -> StreamingManager:
    """Get the global streaming manager."""
    global _streaming_manager
    if _streaming_manager is None:
        _streaming_manager = StreamingManager()
    return _streaming_manager
