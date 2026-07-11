"""Tests for streaming.py (workers version) — Event, EventBus, StreamManager, emission functions."""

import queue
import threading
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from streaming import (
    Event,
    EventType,
    StreamingFindingEmitter,
    StreamManager,
    clear_engagement_rt_fingerprints,
    clear_transactional_emitter,
    emit_agent_decision,
    emit_complete,
    emit_error,
    emit_finding,
    emit_finding_rt,
    emit_posture_update,
    emit_progress,
    emit_report_chunk,
    emit_report_complete,
    emit_state_change,
    emit_swarm_agent_action,
    emit_swarm_agent_complete,
    emit_swarm_agent_started,
    emit_swarm_merge_complete,
    emit_thinking,
    emit_tool_complete,
    emit_tool_output,
    emit_tool_start,
    flush_transactional_events,
    get_stream_manager,
    get_transactional_emitter,
    set_transactional_emitter,
)


class TestEventType:
    def test_constants_exist(self):
        assert EventType.THINKING == "thinking"
        assert EventType.TOOL_OUTPUT == "tool_output"
        assert EventType.TOOL_START == "tool_start"
        assert EventType.TOOL_COMPLETE == "tool_complete"
        assert EventType.FINDING == "finding"
        assert EventType.STATE_CHANGE == "state_change"
        assert EventType.PROGRESS == "progress"
        assert EventType.ERROR == "error"
        assert EventType.COMPLETE == "complete"
        assert EventType.REPORT_CHUNK == "report_chunk"


class TestEvent:
    def test_default_construction(self):
        event = Event(type="test", engagement_id="eng-123")
        assert event.type == "test"
        assert event.engagement_id == "eng-123"
        assert event.data == {}
        assert event.timestamp is not None

    def test_to_dict(self):
        event = Event(type="finding", engagement_id="eng-1", data={"severity": "HIGH"})
        d = event.to_dict()
        assert d["type"] == "finding"
        assert d["engagement_id"] == "eng-1"
        assert d["data"]["severity"] == "HIGH"
        assert "timestamp" in d

    def test_to_sse(self):
        event = Event(type="test", engagement_id="eng-1")
        sse = event.to_sse()
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        assert "test" in sse


class TestStreamManager:
    def test_default_state(self):
        sm = StreamManager()
        assert sm._queues == {}
        assert sm._history == {}
        assert sm._dropped_count == {}

    def test_subscribe_adds_queue(self):
        sm = StreamManager()
        q = sm.subscribe("eng-1")
        assert isinstance(q, queue.Queue)
        assert len(sm._queues["eng-1"]) == 1

    def test_unsubscribe_removes_queue(self):
        sm = StreamManager()
        q = sm.subscribe("eng-1")
        sm.unsubscribe("eng-1", q)
        assert len(sm._queues["eng-1"]) == 0

    def test_publish_delivers_to_subscriber(self):
        sm = StreamManager()
        q = sm.subscribe("eng-1")
        event = Event(type="test", engagement_id="eng-1")
        sm.publish(event)
        received = q.get(timeout=1)
        assert received.type == "test"

    def test_publish_adds_to_history(self):
        sm = StreamManager()
        sm.subscribe("eng-1")
        sm.publish(Event(type="test", engagement_id="eng-1"))
        assert len(sm._history["eng-1"]) == 1

    def test_publish_history_limit(self):
        sm = StreamManager()
        sm.subscribe("eng-1")
        for i in range(600):
            sm.publish(Event(type=f"e{i}", engagement_id="eng-1"))
        assert len(sm._history["eng-1"]) <= 500

    def test_publish_no_engagement_ignored(self):
        sm = StreamManager()
        sm.publish(Event(type="test", engagement_id=""))
        assert sm._history == {}

    def test_get_history_filters_by_since(self):
        sm = StreamManager()
        sm.subscribe("eng-1")
        sm.publish(Event(type="old", engagement_id="eng-1"))
        ts = datetime.now(UTC).isoformat()
        sm.publish(Event(type="new", engagement_id="eng-1"))
        history = sm.get_history("eng-1", since=ts)
        assert len(history) == 1
        assert history[0]["type"] == "new"

    def test_get_history_empty(self):
        sm = StreamManager()
        assert sm.get_history("nonexistent") == []

    def test_clear_engagement(self):
        sm = StreamManager()
        sm.subscribe("eng-1")
        sm.publish(Event(type="test", engagement_id="eng-1"))
        sm.clear_engagement("eng-1")
        assert "eng-1" not in sm._queues
        assert "eng-1" not in sm._history

    def test_get_dropped_count(self):
        sm = StreamManager()
        sm.subscribe("eng-1")
        assert sm.get_dropped_count("eng-1") == 0

    def test_publish_to_all_subscribers(self):
        sm = StreamManager()
        q1 = sm.subscribe("eng-1")
        q2 = sm.subscribe("eng-1")
        sm.publish(Event(type="test", engagement_id="eng-1"))
        q1.get(timeout=1)
        q2.get(timeout=1)
        # Both received — no timeout means success

    def test_unsubscribed_not_notified(self):
        sm = StreamManager()
        q = sm.subscribe("eng-1")
        sm.unsubscribe("eng-1", q)
        sm.publish(Event(type="test", engagement_id="eng-1"))
        with pytest.raises(queue.Empty):
            q.get(timeout=0.3)

    def test_evict_stale_engagements(self):
        sm = StreamManager()
        sm.subscribe("eng-stale")
        sm.publish(
            Event(
                type="old", engagement_id="eng-stale", timestamp="2020-01-01T00:00:00"
            )
        )
        sm.evict_stale_engagements(max_engagement_age_seconds=1)
        assert "eng-stale" not in sm._history

    def test_evict_preserves_fresh(self):
        sm = StreamManager()
        sm.subscribe("eng-fresh")
        sm.publish(Event(type="new", engagement_id="eng-fresh"))
        sm.evict_stale_engagements(max_engagement_age_seconds=86400)
        assert "eng-fresh" in sm._history

    def test_concurrent_access(self):
        """Multiple threads should be able to subscribe/publish/unsubscribe."""
        sm = StreamManager()
        errors = []

        def worker(eid, n):
            try:
                q = sm.subscribe(eid)
                for i in range(10):
                    sm.publish(Event(type=f"e{i}", engagement_id=eid))
                sm.unsubscribe(eid, q)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"eng-{i}", 10)) for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


class TestGetStreamManager:
    def test_singleton(self):
        s1 = get_stream_manager()
        s2 = get_stream_manager()
        assert s1 is s2

    def test_is_streammanager(self):
        sm = get_stream_manager()
        assert isinstance(sm, StreamManager)


class TestStreamingFindingEmitter:
    def test_lazy_stream_init(self):
        emitter = StreamingFindingEmitter("eng-1")
        assert emitter._stream is None
        stream = emitter.stream
        assert stream is not None
        assert emitter._stream is stream


class TestEmitConvenienceFunctions:
    def test_emit_thinking(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_thinking("eng-1", "thinking message", {"key": "val"})
            mock_sm.publish.assert_called_once()

    def test_emit_tool_start(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_tool_start("eng-1", "nuclei", ["-u", "target"])
            mock_sm.publish.assert_called_once()

    def test_emit_tool_output(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_tool_output("eng-1", "nuclei", "line1\nline2")
            mock_sm.publish.assert_called_once()

    def test_emit_tool_complete(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_tool_complete("eng-1", "nuclei", True, 1200, 5)
            mock_sm.publish.assert_called_once()

    def test_emit_finding(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_finding("eng-1", "XSS", "HIGH", "/api", "XSS Found")
            mock_sm.publish.assert_called_once()

    def test_emit_state_change(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_state_change("eng-1", "recon", "scan", "recon complete")
            mock_sm.publish.assert_called_once()

    def test_emit_progress(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_progress("eng-1", "recon", 0.5, "halfway")
            mock_sm.publish.assert_called_once()

    def test_emit_error(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_error("eng-1", "something broke", "scan")
            mock_sm.publish.assert_called_once()

    def test_emit_complete(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_complete("eng-1", "recon", {"findings": 5})
            mock_sm.publish.assert_called_once()

    def test_emit_report_chunk(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_report_chunk("eng-1", "some text")
            mock_sm.publish.assert_called_once()

    def test_emit_report_complete(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_report_complete("eng-1", {"format": "pdf"})
            mock_sm.publish.assert_called_once()

    def test_emit_agent_decision(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_agent_decision("eng-1", 1, "nuclei", "best tool")
            mock_sm.publish.assert_called_once()

    def test_emit_swarm_agent_started(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_swarm_agent_started("eng-1", "xss")
            mock_sm.publish.assert_called_once()

    def test_emit_swarm_agent_action(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_swarm_agent_action("eng-1", "xss", "dalfox", "scanning")
            mock_sm.publish.assert_called_once()

    def test_emit_swarm_agent_complete(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_swarm_agent_complete("eng-1", "xss", 3)
            mock_sm.publish.assert_called_once()

    def test_emit_swarm_merge_complete(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_swarm_merge_complete("eng-1", 10, 2)
            mock_sm.publish.assert_called_once()

    def test_emit_posture_update(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            emit_posture_update("eng-1", 85.0, {"soc2": 90.0}, "improving", 12)
            mock_sm.publish.assert_called_once()

    def test_emit_finding_rt(self):
        with patch("streaming.get_stream_manager") as mock_get:
            mock_sm = MagicMock()
            mock_get.return_value = mock_sm
            finding = {
                "type": "XSS",
                "severity": "HIGH",
                "endpoint": "/api",
                "confidence": 0.9,
            }
            emit_finding_rt("eng-1", finding, "nuclei")
            mock_sm.publish.assert_called_once()


class TestClearEngagementRTFingerprints:
    def test_clear_nonexistent(self):
        """Clearing fingerprints for non-existent engagement should not raise."""
        clear_engagement_rt_fingerprints("nonexistent")


class TestTransactionalEmitter:
    def test_set_and_get(self):
        set_transactional_emitter("test")
        assert get_transactional_emitter() == "test"
        clear_transactional_emitter()
        assert get_transactional_emitter() is None

    def test_flush_no_emitter(self):
        """flush_transactional_events with no emitter should be a no-op."""
        clear_transactional_emitter()
        flush_transactional_events()  # should not raise
