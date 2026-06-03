"""
Tests for the streaming output manager.

Covers:
  - StreamEvent dataclass construction and serialization
  - EventType enum
  - StreamHandler ABC enforcement
  - ConsoleStreamHandler output formatting
  - StreamingManager subscribe/unsubscribe/emit/history
  - Thread safety
  - Singleton pattern
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from argus_cli.streaming.manager import (
    ConsoleStreamHandler,
    EventType,
    StreamEvent,
    StreamHandler,
    StreamingManager,
    get_streaming_manager,
)


# =========================================================================
# EventType Enum
# =========================================================================


class TestEventType:
    """Tests for the EventType enum."""

    def test_all_event_types_have_values(self) -> None:
        assert EventType.THINKING.value == "thinking"
        assert EventType.TOOL_START.value == "tool_start"
        assert EventType.TOOL_OUTPUT.value == "tool_output"
        assert EventType.TOOL_COMPLETE.value == "tool_complete"
        assert EventType.FINDING.value == "finding"
        assert EventType.PROGRESS.value == "progress"
        assert EventType.STATE_CHANGE.value == "state_change"
        assert EventType.ERROR.value == "error"
        assert EventType.COMPLETE.value == "complete"
        assert EventType.REPORT_CHUNK.value == "report_chunk"

    def test_all_types_accounted(self) -> None:
        assert len(EventType) == 10


# =========================================================================
# StreamEvent Dataclass
# =========================================================================


class TestStreamEvent:
    """Tests for the StreamEvent dataclass."""

    def test_default_construction(self) -> None:
        event = StreamEvent(event_type=EventType.THINKING)
        assert event.event_type == EventType.THINKING
        assert event.data == {}
        assert event.timestamp
        assert event.engagement_id == ""

    def test_with_data_and_engagement(self) -> None:
        event = StreamEvent(
            event_type=EventType.TOOL_START,
            data={"tool": "nuclei", "args": ["-target", "example.com"]},
            engagement_id="abc123",
        )
        assert event.data["tool"] == "nuclei"
        assert event.engagement_id == "abc123"

    def test_to_dict_includes_all_fields(self) -> None:
        event = StreamEvent(
            event_type=EventType.FINDING,
            data={"severity": "high", "type": "xss"},
            engagement_id="eid-1",
        )
        d = event.to_dict()
        assert d["type"] == "finding"
        assert d["data"]["severity"] == "high"
        assert d["engagement_id"] == "eid-1"
        assert "timestamp" in d


# =========================================================================
# StreamHandler ABC
# =========================================================================


class TestStreamHandler:
    """Tests for the StreamHandler abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            StreamHandler()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_on_event(self) -> None:
        class BadHandler(StreamHandler):
            pass

        with pytest.raises(TypeError):
            BadHandler()

    def test_concrete_subclass_works(self) -> None:
        class GoodHandler(StreamHandler):
            def on_event(self, event: StreamEvent) -> None:
                self.last = event

        h = GoodHandler()
        event = StreamEvent(event_type=EventType.THINKING)
        h.on_event(event)
        assert h.last is event


# =========================================================================
# ConsoleStreamHandler
# =========================================================================


class TestConsoleStreamHandler:
    """Tests for ConsoleStreamHandler output formatting."""

    def test_tool_start(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.TOOL_START, data={"tool": "nuclei"})
        handler.on_event(event)
        mock_console.print.assert_called_once()
        assert "Running nuclei" in str(mock_console.print.call_args[0][0])

    def test_tool_output(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.TOOL_OUTPUT, data={"output": "line1\nline2\nline3"})
        handler.on_event(event)
        assert mock_console.print.call_count == 3

    def test_tool_output_empty(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.TOOL_OUTPUT, data={"output": ""})
        handler.on_event(event)
        mock_console.print.assert_not_called()

    def test_tool_output_truncated(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.TOOL_OUTPUT, data={"output": "\n".join(f"line{i}" for i in range(20))})
        handler.on_event(event)
        assert mock_console.print.call_count == 10  # max 10 lines

    def test_tool_complete_success(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.TOOL_COMPLETE, data={"tool": "nuclei", "success": True})
        handler.on_event(event)
        output = str(mock_console.print.call_args[0][0])
        assert "✓" in output
        assert "nuclei" in output

    def test_tool_complete_failure(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.TOOL_COMPLETE, data={"tool": "ffuf", "success": False})
        handler.on_event(event)
        output = str(mock_console.print.call_args[0][0])
        assert "✗" in output
        assert "ffuf" in output

    def test_finding_critical(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(
            event_type=EventType.FINDING,
            data={"severity": "critical", "type": "sql_injection", "endpoint": "/api/login"},
        )
        handler.on_event(event)
        output = str(mock_console.print.call_args[0][0])
        assert "CRITICAL" in output
        assert "/api/login" in output

    def test_finding_low(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(
            event_type=EventType.FINDING,
            data={"severity": "low", "type": "info_leak", "endpoint": "/robots.txt"},
        )
        handler.on_event(event)
        output = str(mock_console.print.call_args[0][0])
        assert "LOW" in output

    def test_progress(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.PROGRESS, data={"phase": "scanning", "percent": 75})
        handler.on_event(event)
        output = str(mock_console.print.call_args[0][0])
        assert "75%" in output
        assert "scanning" in output

    def test_error(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.ERROR, data={"error": "Connection refused"})
        handler.on_event(event)
        output = str(mock_console.print.call_args[0][0])
        assert "Error:" in output
        assert "Connection refused" in output

    def test_thinking_event_prints_nothing(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.THINKING, data={"thought": "..."})
        handler.on_event(event)
        mock_console.print.assert_not_called()

    def test_state_change_event_prints_nothing(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.STATE_CHANGE, data={"from": "idle", "to": "scanning"})
        handler.on_event(event)
        mock_console.print.assert_not_called()

    def test_complete_event_prints_nothing(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.COMPLETE, data={"status": "done"})
        handler.on_event(event)
        mock_console.print.assert_not_called()

    def test_report_chunk_event_prints_nothing(self) -> None:
        mock_console = MagicMock()
        handler = ConsoleStreamHandler(console=mock_console)
        event = StreamEvent(event_type=EventType.REPORT_CHUNK, data={"chunk": "..."})
        handler.on_event(event)
        mock_console.print.assert_not_called()

    def test_console_auto_create(self) -> None:
        """ConsoleStreamHandler should create its own Console if none given."""
        handler = ConsoleStreamHandler()
        assert handler.console is None
        # on_event uses a lazy import of rich.console.Console
        with patch("rich.console.Console") as mock_console_cls:
            mock_console = MagicMock()
            mock_console_cls.return_value = mock_console
            event = StreamEvent(event_type=EventType.TOOL_START, data={"tool": "test"})
            handler.on_event(event)
            assert handler.console is mock_console


# =========================================================================
# StreamingManager
# =========================================================================


class TestStreamingManager:
    """Tests for the StreamingManager class."""

    def test_default_state(self) -> None:
        manager = StreamingManager()
        assert manager._handlers == []
        assert manager._history == []

    def test_subscribe_adds_handler(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)
        assert handler in manager._handlers

    def test_unsubscribe_removes_handler(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)
        manager.unsubscribe(handler)
        assert handler not in manager._handlers

    def test_unsubscribe_nonexistent_does_not_raise(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.unsubscribe(handler)  # should not raise

    def test_emit_notifies_subscribers(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)

        event = StreamEvent(event_type=EventType.THINKING)
        manager.emit(event)
        handler.on_event.assert_called_once_with(event)

    def test_emit_notifies_all_subscribers(self) -> None:
        manager = StreamingManager()
        h1 = MagicMock(spec=StreamHandler)
        h2 = MagicMock(spec=StreamHandler)
        manager.subscribe(h1)
        manager.subscribe(h2)

        event = StreamEvent(event_type=EventType.THINKING)
        manager.emit(event)
        h1.on_event.assert_called_once_with(event)
        h2.on_event.assert_called_once_with(event)

    def test_emit_adds_to_history(self) -> None:
        manager = StreamingManager()
        event = StreamEvent(event_type=EventType.THINKING)
        manager.emit(event)
        assert len(manager._history) == 1
        assert manager._history[0] is event

    def test_emit_history_limit(self) -> None:
        manager = StreamingManager()
        for i in range(600):
            manager.emit(StreamEvent(event_type=EventType.THINKING, data={"i": i}))
        assert len(manager._history) == 500  # max 500

    def test_emit_isolates_handler_exceptions(self) -> None:
        """One handler failing should not prevent others from receiving events."""
        manager = StreamingManager()
        good = MagicMock(spec=StreamHandler)
        bad = MagicMock(spec=StreamHandler)
        bad.on_event.side_effect = RuntimeError("Handler crashed")

        manager.subscribe(good)
        manager.subscribe(bad)

        event = StreamEvent(event_type=EventType.THINKING)
        manager.emit(event)  # should not raise

        good.on_event.assert_called_once_with(event)

    def test_unsubscribed_handler_not_notified(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)
        manager.unsubscribe(handler)

        event = StreamEvent(event_type=EventType.THINKING)
        manager.emit(event)
        handler.on_event.assert_not_called()

    def test_emit_tool_start(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)

        manager.emit_tool_start("eid-1", "nuclei", ["-target", "example.com"])
        event = handler.on_event.call_args[0][0]
        assert event.event_type == EventType.TOOL_START
        assert event.data["tool"] == "nuclei"
        assert event.engagement_id == "eid-1"

    def test_emit_tool_output(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)

        manager.emit_tool_output("eid-1", "nuclei", "scan results")
        event = handler.on_event.call_args[0][0]
        assert event.event_type == EventType.TOOL_OUTPUT
        assert event.data["output"] == "scan results"

    def test_emit_tool_complete(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)

        manager.emit_tool_complete("eid-1", "nuclei", success=True, duration_ms=1500)
        event = handler.on_event.call_args[0][0]
        assert event.event_type == EventType.TOOL_COMPLETE
        assert event.data["success"] is True
        assert event.data["duration_ms"] == 1500

    def test_emit_finding(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)

        finding = {"severity": "high", "type": "xss", "endpoint": "/search"}
        manager.emit_finding("eid-1", finding)
        event = handler.on_event.call_args[0][0]
        assert event.event_type == EventType.FINDING
        assert event.data["severity"] == "high"

    def test_emit_progress(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)

        manager.emit_progress("eid-1", "scanning", 50)
        event = handler.on_event.call_args[0][0]
        assert event.event_type == EventType.PROGRESS
        assert event.data["phase"] == "scanning"
        assert event.data["percent"] == 50

    def test_emit_error(self) -> None:
        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)

        manager.emit_error("eid-1", "Something broke")
        event = handler.on_event.call_args[0][0]
        assert event.event_type == EventType.ERROR
        assert event.data["error"] == "Something broke"

    def test_get_history_filters_by_engagement(self) -> None:
        manager = StreamingManager()
        manager.emit_tool_start("eid-1", "nuclei", [])
        manager.emit_tool_start("eid-2", "ffuf", [])
        manager.emit_tool_start("eid-1", "httpx", [])

        history = manager.get_history("eid-1")
        assert len(history) == 2
        assert all(e.engagement_id == "eid-1" for e in history)

    def test_get_history_empty(self) -> None:
        manager = StreamingManager()
        history = manager.get_history("nonexistent")
        assert history == []


# =========================================================================
# Thread Safety
# =========================================================================


class TestStreamingManagerThreadSafety:
    """Tests for thread-safe behavior of StreamingManager."""

    def test_concurrent_emit_does_not_crash(self) -> None:
        import threading

        manager = StreamingManager()
        handler = MagicMock(spec=StreamHandler)
        manager.subscribe(handler)

        errors = []

        def emit_events() -> None:
            try:
                for i in range(100):
                    manager.emit_tool_start("eid", "tool", [str(i)])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=emit_events) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(manager._history) == 400  # 4 * 100 = 400

    def test_concurrent_subscribe_unsubscribe(self) -> None:
        import threading

        manager = StreamingManager()
        errors = []

        def add_and_remove() -> None:
            try:
                for _ in range(50):
                    h = MagicMock(spec=StreamHandler)
                    manager.subscribe(h)
                    manager.unsubscribe(h)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_and_remove) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =========================================================================
# Singleton Pattern
# =========================================================================


class TestGetStreamingManager:
    """Tests for the get_streaming_manager singleton."""

    def test_returns_same_instance(self) -> None:
        # Reset the singleton global for testing
        import argus_cli.streaming.manager as sm

        old = sm._streaming_manager
        sm._streaming_manager = None
        try:
            m1 = get_streaming_manager()
            m2 = get_streaming_manager()
            assert m1 is m2
        finally:
            sm._streaming_manager = old

    def test_singleton_preserves_state(self) -> None:
        import argus_cli.streaming.manager as sm

        old = sm._streaming_manager
        sm._streaming_manager = None
        try:
            manager = get_streaming_manager()
            manager.emit_tool_start("eid", "test", [])
            assert len(manager.get_history("eid")) == 1
            # Same instance
            same = get_streaming_manager()
            assert len(same.get_history("eid")) == 1
        finally:
            sm._streaming_manager = old
