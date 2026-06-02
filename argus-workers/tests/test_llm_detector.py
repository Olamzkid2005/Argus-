"""
Tests for LLM Detector - Post-response intelligence.
"""
import json
from unittest.mock import MagicMock

import pytest

from tools.llm_detector import LLMDetector


class MockResponse:
    """Mock HTTP response for testing."""
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = MagicMock()
    client.is_available.return_value = True
    client.model = "gpt-4o-mini"
    return client


@pytest.fixture
def detector(mock_llm_client):
    """Create LLMDetector with mock client."""
    return LLMDetector(llm_client=mock_llm_client)


class TestLLMDetector:
    """Test suite for LLMDetector."""

    def test_analyze_structured_output(self, detector):
        """Test that structured output parsing works for vulnerable response."""
        result = detector._parse_response(json.dumps({
            "vulnerable": True,
            "confidence": 0.85,
            "evidence_quote": "<script>alert(1)</script>",
            "vuln_type": "XSS",
            "reasoning": "Payload reflected unencoded in response body",
        }))
        assert result is not None
        assert result.vulnerable is True
        assert result.confidence == 0.85
        assert result.vuln_type == "XSS"

    def test_analyze_not_vulnerable(self, detector):
        """Test that non-vulnerable response is correctly parsed."""
        result = detector._parse_response(json.dumps({
            "vulnerable": False,
            "confidence": 0.0,
            "evidence_quote": "",
            "vuln_type": "XSS",
            "reasoning": "No evidence of successful exploitation detected",
        }))
        assert result is not None
        assert result.vulnerable is False
        assert result.confidence == 0.0

    def test_analyze_async_unavailable_returns_none(self):
        """Test graceful degradation when LLM is unavailable."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        detector = LLMDetector(llm_client=mock_client)

        assert detector.analyze_sync("http://example.com/", "XSS", "test", MockResponse(status_code=200, text="test")) is None

    def test_analyze_error_returns_none(self, detector):
        """Test parsing of invalid response returns None."""
        result = detector._parse_response("{invalid json}")
        assert result is None

    def test_should_skip_high_confidence(self, detector):
        """Test skip logic for high confidence findings."""
        finding = {"confidence": 0.85, "evidence": {"payload": "test"}}
        assert detector.should_skip(finding, MockResponse()) is True

    def test_should_skip_low_confidence(self, detector):
        """Test skip logic for very low confidence findings."""
        finding = {"confidence": 0.2, "evidence": {"payload": "test"}}
        assert detector.should_skip(finding, MockResponse()) is True

    def test_should_not_skip_candidate(self, detector):
        """Test that candidate findings are not skipped."""
        finding = {"confidence": 0.5, "evidence": {"payload": "<script>alert(1)</script>"}}
        response = MockResponse(text="<html><body>This is a sufficiently long response body with enough content to pass the 50 character minimum length check for LLM analysis.</body></html>")
        assert detector.should_skip(finding, response) is False

    def test_should_skip_no_evidence(self, detector):
        """Test skip logic for findings with no payload or response evidence."""
        finding = {"confidence": 0.5, "evidence": {}}
        assert detector.should_skip(finding, MockResponse()) is True

    def test_parse_response_json(self, detector):
        """Test parsing of valid JSON response."""
        raw = '{"vulnerable": true, "confidence": 0.9, "evidence_quote": "test", "vuln_type": "SQL_INJECTION", "reasoning": "test"}'
        result = detector._parse_response(raw)
        assert result is not None
        assert result.vulnerable is True
        assert result.confidence == 0.9
        assert result.vuln_type == "SQL_INJECTION"

    def test_parse_response_markdown_json(self, detector):
        """Test parsing of JSON inside markdown code block."""
        raw = '```json\n{"vulnerable": true, "confidence": 0.75, "evidence_quote": "error in sql", "vuln_type": "SQL_INJECTION", "reasoning": "test"}\n```'
        result = detector._parse_response(raw)
        assert result is not None
        assert result.vulnerable is True
        assert result.confidence == 0.75

    def test_parse_response_invalid(self, detector):
        """Test parsing of invalid response returns None."""
        result = detector._parse_response("not json at all")
        assert result is None

    def test_analyze_with_context(self, detector):
        """Test that context dict is accepted (via _parse_response)."""
        result = detector._parse_response(json.dumps({
            "vulnerable": True,
            "confidence": 0.8,
            "evidence_quote": "49",
            "vuln_type": "SSTI",
            "reasoning": "Template expression evaluated to 49",
        }))
        assert result is not None
        assert result.vulnerable is True
        assert result.vuln_type == "SSTI"
