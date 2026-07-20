"""
Tests for emit_event() shared helper and all emit_* convenience functions.

Verifies that every emit_* function produces the correct EventType constant
and correctly structured data payload when published to the stream manager.
"""


import pytest

from streaming import (
    ErrorHint,
    EventType,
    clear_transactional_emitter,
    emit_agent_decision,
    emit_complete,
    emit_error,
    emit_error_hint,
    emit_event,
    emit_finding,
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
    get_stream_manager,
    set_transactional_emitter,
)

ENGAGEMENT_ID = "test-eng-001"


# ── emit_event() helper ──


class TestEmitEvent:
    """Tests for the emit_event() shared helper."""

    def test_publishes_event(self):
        """emit_event should publish an Event to the stream manager."""
        sm = get_stream_manager()
        # Subscribe so we can read the event
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_event(ENGAGEMENT_ID, EventType.THINKING, {"message": "hello"})
            event = q.get(timeout=1)
            assert event.type == EventType.THINKING
            assert event.engagement_id == ENGAGEMENT_ID
            assert event.data == {"message": "hello"}
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_publishes_correct_data_shape(self):
        """emit_event should publish the exact data dict provided."""
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            data = {"tool": "nuclei", "args": ["-u", "http://test.com"]}
            emit_event(ENGAGEMENT_ID, EventType.TOOL_START, data)
            event = q.get(timeout=1)
            assert event.data == data
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_delegates_to_transactional_emitter(self):
        """When a transactional emitter is active, emit_event should delegate."""
        class MockEmitter:
            def __init__(self):
                self.calls = []

            def emit_thinking(self, message, details):
                self.calls.append(("thinking", message, details))

            def flush(self):
                pass

        emitter = MockEmitter()
        set_transactional_emitter(emitter)
        try:
            emit_event(ENGAGEMENT_ID, EventType.THINKING, {"message": "txn test"})
            assert len(emitter.calls) == 1
            assert emitter.calls[0] == ("thinking", "txn test", None)
        finally:
            clear_transactional_emitter()

    def test_unknown_event_type_with_transactional(self):
        """Unhandled event types should fall through to direct publish."""
        class MockEmitter:
            def flush(self):
                pass

        emitter = MockEmitter()
        set_transactional_emitter(emitter)
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            # PROGRESS is not handled by _maybe_transactional → falls through
            emit_event(ENGAGEMENT_ID, EventType.PROGRESS, {"phase": "scan", "progress": 0.5})
            event = q.get(timeout=1)
            assert event.type == EventType.PROGRESS
        finally:
            clear_transactional_emitter()
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_empty_engagement_id_skips_publish(self):
        """Events with empty engagement_id should not be published."""
        sm = get_stream_manager()
        # Subscribe to a known engagement — events without engagement_id
        # should skip the publish call entirely (early return in StreamManager)
        q = sm.subscribe("other-eng")
        try:
            emit_event("", EventType.THINKING, {"message": "skip"})
            # Should not hang — the event should not be published
            import queue
            with pytest.raises(queue.Empty):
                q.get(timeout=0.5)
        finally:
            sm.unsubscribe("other-eng", q)





# ── emit_thinking ──


class TestEmitThinking:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_thinking(ENGAGEMENT_ID, "analyzing target", {"detail": "foo"})
            event = q.get(timeout=1)
            assert event.type == EventType.THINKING
            assert event.data["message"] == "analyzing target"
            assert event.data["details"] == {"detail": "foo"}
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_default_details(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_thinking(ENGAGEMENT_ID, "no details")
            event = q.get(timeout=1)
            assert event.data["message"] == "no details"
            assert event.data["details"] == {}
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_tool_start ──


class TestEmitToolStart:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_tool_start(ENGAGEMENT_ID, "nuclei", ["-u", "http://test.com"])
            event = q.get(timeout=1)
            assert event.type == EventType.TOOL_START
            assert event.data["tool"] == "nuclei"
            assert event.data["args"] == ["-u", "http://test.com"]
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_default_args(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_tool_start(ENGAGEMENT_ID, "nmap")
            event = q.get(timeout=1)
            assert event.data["tool"] == "nmap"
            assert event.data["args"] == []
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_tool_output ──


class TestEmitToolOutput:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_tool_output(ENGAGEMENT_ID, "nuclei", "finding: xss", is_stderr=False)
            event = q.get(timeout=1)
            assert event.type == EventType.TOOL_OUTPUT
            assert event.data["tool"] == "nuclei"
            assert event.data["output"] == "finding: xss"
            assert event.data["is_stderr"] is False
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_stderr(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_tool_output(ENGAGEMENT_ID, "nuclei", "error msg", is_stderr=True)
            event = q.get(timeout=1)
            assert event.data["is_stderr"] is True
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_tool_complete ──


class TestEmitToolComplete:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_tool_complete(ENGAGEMENT_ID, "nuclei", True, 1500, finding_count=3)
            event = q.get(timeout=1)
            assert event.type == EventType.TOOL_COMPLETE
            assert event.data["tool"] == "nuclei"
            assert event.data["success"] is True
            assert event.data["duration_ms"] == 1500
            assert event.data["findings"] == 3
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_default_finding_count(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_tool_complete(ENGAGEMENT_ID, "nuclei", True, 500)
            event = q.get(timeout=1)
            assert event.data["findings"] == 0
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_finding ──


class TestEmitFinding:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_finding(
                ENGAGEMENT_ID, "XSS", "HIGH", "/api", "XSS in search param"
            )
            event = q.get(timeout=1)
            assert event.type == EventType.FINDING
            assert event.data["type"] == "XSS"
            assert event.data["severity"] == "HIGH"
            assert event.data["endpoint"] == "/api"
            assert event.data["title"] == "XSS in search param"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_with_optional_params(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_finding(
                ENGAGEMENT_ID, "SQLI", "CRITICAL", "/login", "SQL injection",
                confidence=0.95, source_tool="sqlmap",
            )
            event = q.get(timeout=1)
            assert event.data["type"] == "SQLI"
            assert event.data["confidence"] == 0.95
            assert event.data["source_tool"] == "sqlmap"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_without_optional_params(self):
        """Optional params confidence and source_tool should not appear when None."""
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_finding(
                ENGAGEMENT_ID, "INFO", "LOW", "/robots.txt", "robots.txt"
            )
            event = q.get(timeout=1)
            assert "confidence" not in event.data
            assert "source_tool" not in event.data
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_state_change ──


class TestEmitStateChange:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_state_change(ENGAGEMENT_ID, "scanning", "analyzing", "Scan complete")
            event = q.get(timeout=1)
            assert event.type == EventType.STATE_CHANGE
            assert event.data["from"] == "scanning"
            assert event.data["to"] == "analyzing"
            assert event.data["reason"] == "Scan complete"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_default_reason(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_state_change(ENGAGEMENT_ID, "recon", "scan")
            event = q.get(timeout=1)
            assert event.data["reason"] == ""
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_progress ──


class TestEmitProgress:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_progress(ENGAGEMENT_ID, "scan", 0.75, "75% complete")
            event = q.get(timeout=1)
            assert event.type == EventType.PROGRESS
            assert event.data["phase"] == "scan"
            assert event.data["progress"] == 0.75
            assert event.data["message"] == "75% complete"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_default_message(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_progress(ENGAGEMENT_ID, "recon", 0.5)
            event = q.get(timeout=1)
            assert event.data["message"] == ""
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_error ──


class TestEmitError:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_error(ENGAGEMENT_ID, "Connection refused", phase="scan")
            event = q.get(timeout=1)
            assert event.type == EventType.ERROR
            assert event.data["error"] == "Connection refused"
            assert event.data["phase"] == "scan"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_default_phase(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_error(ENGAGEMENT_ID, "Generic error")
            event = q.get(timeout=1)
            assert event.data["phase"] == ""
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_error_hint ──


class TestEmitErrorHint:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            hint = ErrorHint(
                summary="Rate limit hit",
                detail="Too many requests",
                remediation="Slow down",
                hint_command="--rate-limit 10",
                docs_url="https://docs.argus.io/rate-limit",
                tool="nuclei",
                error_id="RATE_LIMITED",
            )
            emit_error_hint(ENGAGEMENT_ID, hint)
            event = q.get(timeout=1)
            assert event.type == EventType.ERROR_HINT
            assert event.data["summary"] == "Rate limit hit"
            assert event.data["detail"] == "Too many requests"
            assert event.data["remediation"] == "Slow down"
            assert event.data["hint_command"] == "--rate-limit 10"
            assert event.data["docs_url"] == "https://docs.argus.io/rate-limit"
            assert event.data["tool"] == "nuclei"
            assert event.data["error_id"] == "RATE_LIMITED"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_complete ──


class TestEmitComplete:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_complete(ENGAGEMENT_ID, "scan", {"findings": 5, "duration": 120})
            event = q.get(timeout=1)
            assert event.type == EventType.COMPLETE
            assert event.data["phase"] == "scan"
            assert event.data["summary"] == {"findings": 5, "duration": 120}
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_default_summary(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_complete(ENGAGEMENT_ID, "recon")
            event = q.get(timeout=1)
            assert event.data["summary"] == {}
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_report_chunk ──


class TestEmitReportChunk:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_report_chunk(ENGAGEMENT_ID, "## Executive Summary")
            event = q.get(timeout=1)
            assert event.type == EventType.REPORT_CHUNK
            assert event.data["text"] == "## Executive Summary"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_report_complete ──


class TestEmitReportComplete:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_report_complete(ENGAGEMENT_ID, {"total_pages": 3, "format": "markdown"})
            event = q.get(timeout=1)
            assert event.type == EventType.REPORT_COMPLETE
            assert event.data["summary"] == {"total_pages": 3, "format": "markdown"}
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_default_summary(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_report_complete(ENGAGEMENT_ID)
            event = q.get(timeout=1)
            assert event.data["summary"] == {}
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_agent_decision ──


class TestEmitAgentDecision:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_agent_decision(
                ENGAGEMENT_ID, iteration=3, tool="nuclei",
                reasoning="Found SQL patterns, using nuclei for verification",
                was_fallback=False, agent_domain="sqli",
            )
            event = q.get(timeout=1)
            assert event.type == EventType.AGENT_DECISION
            assert event.data["iteration"] == 3
            assert event.data["tool"] == "nuclei"
            assert "SQL patterns" in event.data["reasoning"]
            assert event.data["was_fallback"] is False
            assert event.data["agent_domain"] == "sqli"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_reasoning_truncated(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            long_reason = "x" * 500
            emit_agent_decision(
                ENGAGEMENT_ID, iteration=1, tool="test", reasoning=long_reason,
            )
            event = q.get(timeout=1)
            assert len(event.data["reasoning"]) == 200
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_empty_reasoning(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_agent_decision(
                ENGAGEMENT_ID, iteration=1, tool="test", reasoning="",
            )
            event = q.get(timeout=1)
            assert event.data["reasoning"] == ""
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── Swarm agent events ──


class TestEmitSwarmEvents:
    def test_swarm_agent_started(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_swarm_agent_started(ENGAGEMENT_ID, "xss")
            event = q.get(timeout=1)
            assert event.type == EventType.SWARM_AGENT_STARTED
            assert event.data["domain"] == "xss"
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_swarm_agent_action(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_swarm_agent_action(
                ENGAGEMENT_ID, "sqli", "sqlmap", "Testing injection", iteration=2,
            )
            event = q.get(timeout=1)
            assert event.type == EventType.SWARM_AGENT_ACTION
            assert event.data["domain"] == "sqli"
            assert event.data["tool"] == "sqlmap"
            assert event.data["iteration"] == 2
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_swarm_agent_action_reasoning_truncated(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_swarm_agent_action(
                ENGAGEMENT_ID, "xss", "dalfox", "x" * 500,
            )
            event = q.get(timeout=1)
            assert len(event.data["reasoning"]) == 200
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_swarm_agent_complete(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_swarm_agent_complete(ENGAGEMENT_ID, "sqli", findings_count=7)
            event = q.get(timeout=1)
            assert event.type == EventType.SWARM_AGENT_COMPLETE
            assert event.data["domain"] == "sqli"
            assert event.data["findings_count"] == 7
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)

    def test_swarm_merge_complete(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_swarm_merge_complete(ENGAGEMENT_ID, total_findings=42, dedup_removed=5)
            event = q.get(timeout=1)
            assert event.type == EventType.SWARM_MERGE_COMPLETE
            assert event.data["total_findings"] == 42
            assert event.data["dedup_removed"] == 5
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)


# ── emit_posture_update ──


class TestEmitPostureUpdate:
    def test_basic(self):
        sm = get_stream_manager()
        q = sm.subscribe(ENGAGEMENT_ID)
        try:
            emit_posture_update(
                ENGAGEMENT_ID,
                composite_score=72.5,
                framework_scores={"SOC2": 80, "ISO27001": 65},
                trend="improving",
                total_findings=12,
            )
            event = q.get(timeout=1)
            assert event.type == EventType.POSTURE_UPDATE
            assert event.data["composite_score"] == 72.5
            assert event.data["framework_scores"] == {"SOC2": 80, "ISO27001": 65}
            assert event.data["trend"] == "improving"
            assert event.data["total_findings"] == 12
        finally:
            sm.unsubscribe(ENGAGEMENT_ID, q)
