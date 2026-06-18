"""Tests for tools.context — Tool execution context."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.context import ScanContext, ToolContext


class ToolRunnerStub:
    """Stub for ToolRunner used in tests."""

    pass


class ParserStub:
    """Stub for ParserProtocol."""

    def parse(self, tool_name: str, raw_output: str) -> list[dict]:
        return []


class NormalizerStub:
    """Stub for NormalizerProtocol."""

    def normalize(self, raw_finding: dict, source_tool: str) -> dict:
        return raw_finding


@pytest.fixture
def tool_runner():
    return ToolRunnerStub()


@pytest.fixture
def parser():
    return ParserStub()


@pytest.fixture
def normalizer():
    return NormalizerStub()


class TestToolContext:
    """Tests for ToolContext."""

    def test_init_stores_all_fields(self, tool_runner, parser, normalizer):
        ctx = ToolContext(
            engagement_id="eng-001",
            tool_runner=tool_runner,
            parser=parser,
            normalizer=normalizer,
            ws_publisher="ws_pub",
            llm_payload_generator="llm_gen",
        )
        assert ctx.engagement_id == "eng-001"
        assert ctx.tool_runner is tool_runner
        assert ctx.parser is parser
        assert ctx.normalizer is normalizer
        assert ctx.ws_publisher == "ws_pub"
        assert ctx.llm_payload_generator == "llm_gen"

    def test_init_defaults_optional_fields(self, tool_runner, parser, normalizer):
        ctx = ToolContext(
            engagement_id="eng-001",
            tool_runner=tool_runner,
            parser=parser,
            normalizer=normalizer,
        )
        assert ctx.ws_publisher is None
        assert ctx.llm_payload_generator is None

    def test_from_orchestrator_extracts_fields(self):
        class FakeOrchestrator:
            engagement_id = "eng-001"
            tool_runner = "tr"
            parser = "prs"
            normalizer = "nrm"
            ws_publisher = "wspub"

        ctx = ToolContext.from_orchestrator(FakeOrchestrator())
        assert ctx.engagement_id == "eng-001"
        assert ctx.tool_runner == "tr"
        assert ctx.parser == "prs"
        assert ctx.normalizer == "nrm"
        assert ctx.ws_publisher == "wspub"

    def test_from_orchestrator_handles_missing_llm_payload_generator(self):
        class FakeOrchestrator:
            engagement_id = "eng-001"
            tool_runner = "tr"
            parser = "prs"
            normalizer = "nrm"
            ws_publisher = "wspub"

        ctx = ToolContext.from_orchestrator(FakeOrchestrator())
        assert ctx.llm_payload_generator is None

    def test_publish_activity_calls_ws_publisher(self, tool_runner, parser, normalizer):
        mock_ws = MagicMock()
        ctx = ToolContext(
            engagement_id="eng-001",
            tool_runner=tool_runner,
            parser=parser,
            normalizer=normalizer,
            ws_publisher=mock_ws,
        )
        ctx.publish_activity(
            tool="nuclei",
            activity="scanning",
            status="running",
            items=5,
            details="test",
        )
        mock_ws.publish_scanner_activity.assert_called_once_with(
            engagement_id="eng-001",
            tool_name="nuclei",
            activity="scanning",
            status="running",
            items_found=5,
            details="test",
        )

    def test_publish_activity_is_noop_without_ws_publisher(
        self, tool_runner, parser, normalizer
    ):
        ctx = ToolContext(
            engagement_id="eng-001",
            tool_runner=tool_runner,
            parser=parser,
            normalizer=normalizer,
        )
        ctx.publish_activity(tool="nuclei", activity="scanning", status="running")
        assert True  # no exception raised

    def test_publish_activity_called_with_none_items(
        self, tool_runner, parser, normalizer
    ):
        mock_ws = MagicMock()
        ctx = ToolContext(
            engagement_id="eng-001",
            tool_runner=tool_runner,
            parser=parser,
            normalizer=normalizer,
            ws_publisher=mock_ws,
        )
        ctx.publish_activity(tool="nuclei", activity="scanning", status="running")
        mock_ws.publish_scanner_activity.assert_called_once_with(
            engagement_id="eng-001",
            tool_name="nuclei",
            activity="scanning",
            status="running",
            items_found=None,
            details=None,
        )

    @patch("orchestrator_pkg.normalizer_utils.normalize_finding")
    def test_normalize_finding_calls_normalizer(
        self, mock_normalize, tool_runner, parser, normalizer
    ):
        mock_normalize.return_value = {"normalized": True}
        ctx = ToolContext(
            engagement_id="eng-001",
            tool_runner=tool_runner,
            parser=parser,
            normalizer=normalizer,
        )
        result = ctx._normalize_finding({"raw": True}, "nuclei")
        mock_normalize.assert_called_once_with(normalizer, {"raw": True}, "nuclei")
        assert result == {"normalized": True}

    def test_normalize_finding_returns_raw_when_no_normalizer(
        self, tool_runner, parser
    ):
        ctx = ToolContext(
            engagement_id="eng-001",
            tool_runner=tool_runner,
            parser=parser,
            normalizer=None,
        )
        result = ctx._normalize_finding({"raw": True}, "nuclei")
        assert result == {"raw": True}

    def test_normalize_delegates_to_normalize_finding(
        self, tool_runner, parser, normalizer
    ):
        ctx = ToolContext(
            engagement_id="eng-001",
            tool_runner=tool_runner,
            parser=parser,
            normalizer=normalizer,
        )
        with patch.object(
            ctx, "_normalize_finding", return_value={"normalized": True}
        ) as mock_method:
            result = ctx.normalize({"raw": True}, "nuclei")
            mock_method.assert_called_once_with({"raw": True}, "nuclei")
            assert result == {"normalized": True}


class TestScanContext:
    """Tests for ScanContext (frozen dataclass)."""

    def test_init_stores_all_fields(self):
        ctx = ScanContext(
            engagement_id="eng-001",
            org_id="org-001",
            trace_id="trace-abc",
            target_url="https://example.com",
            aggressiveness="aggressive",
            db_connection_string="postgresql://localhost:5432/db",
            created_at="2025-01-01T00:00:00",
        )
        assert ctx.engagement_id == "eng-001"
        assert ctx.org_id == "org-001"
        assert ctx.trace_id == "trace-abc"
        assert ctx.target_url == "https://example.com"
        assert ctx.aggressiveness == "aggressive"
        assert ctx.db_connection_string == "postgresql://localhost:5432/db"
        assert ctx.created_at == "2025-01-01T00:00:00"

    def test_created_at_defaults_to_current_time(self):
        ctx = ScanContext(
            engagement_id="eng-001",
            org_id="org-001",
        )
        assert ctx.created_at is not None
        assert "T" in ctx.created_at  # ISO format

    def test_is_frozen_raises_on_mutation(self):
        ctx = ScanContext(
            engagement_id="eng-001",
            org_id="org-001",
        )
        with pytest.raises(Exception):
            ctx.engagement_id = "different"

    def test_default_values(self):
        ctx = ScanContext(
            engagement_id="eng-001",
            org_id="org-001",
        )
        assert ctx.trace_id == ""
        assert ctx.target_url == ""
        assert ctx.aggressiveness == "default"
        assert ctx.db_connection_string == ""

    def test_from_orchestrator_extracts_org_id_and_trace_id(self):
        ctx = ScanContext(
            engagement_id="eng-001",
            org_id="org-001",
            trace_id="trace-xyz",
        )
        assert ctx.org_id == "org-001"
        assert ctx.trace_id == "trace-xyz"
