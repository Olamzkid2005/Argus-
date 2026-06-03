"""Tests for tool_core/finding_builder.py — FindingBuilder."""

import pytest

from tool_core.finding_builder import FindingBuilder


class TestFindingBuilder:
    def test_init(self):
        builder = FindingBuilder(source_tool="nuclei")
        assert builder.source_tool == "nuclei"
        assert builder.findings == []

    def test_add_creates_finding(self):
        builder = FindingBuilder(source_tool="nuclei")
        finding = builder.add("XSS", "HIGH", "/api", {"payload": "<script>"})
        assert finding["type"] == "XSS"
        assert finding["severity"] == "HIGH"
        assert finding["endpoint"] == "/api"
        assert finding["source_tool"] == "nuclei"
        assert finding["confidence"] == 0.8

    def test_add_with_extra_fields(self):
        builder = FindingBuilder(source_tool="nuclei")
        finding = builder.add("SQLI", "CRITICAL", "/api/login", {"sql": "1=1"}, confidence=0.95, cve="CVE-2024-0001")
        assert finding["cve"] == "CVE-2024-0001"
        assert finding["confidence"] == 0.95

    def test_clamps_confidence(self):
        builder = FindingBuilder(source_tool="test")
        finding = builder.add("XSS", "HIGH", "/api", {}, confidence=2.5)
        assert finding["confidence"] == 1.0
        finding = builder.add("XSS", "HIGH", "/api", {}, confidence=-0.5)
        assert finding["confidence"] == 0.0

    def test_add_invalid_severity(self):
        builder = FindingBuilder(source_tool="test")
        with pytest.raises(ValueError, match="Invalid severity"):
            builder.add("XSS", "INVALID", "/api", {})

    def test_severity_case_insensitive(self):
        builder = FindingBuilder(source_tool="test")
        finding = builder.add("XSS", "high", "/api", {})
        assert finding["severity"] == "HIGH"

    def test_vulnerability_convenience(self):
        builder = FindingBuilder(source_tool="nuclei")
        finding = builder.vulnerability("SQLI", "CRITICAL", "/api", {"evidence": "test"})
        assert finding["type"] == "SQLI"
        assert finding["severity"] == "CRITICAL"

    def test_info_convenience(self):
        builder = FindingBuilder(source_tool="nuclei")
        finding = builder.info("PARAM_DISCOVERY", "/api", {"param": "id"})
        assert finding["type"] == "PARAM_DISCOVERY"
        assert finding["severity"] == "INFO"

    def test_findings_property_returns_copy(self):
        builder = FindingBuilder(source_tool="test")
        builder.add("XSS", "HIGH", "/api", {})
        f = builder.findings
        assert len(f) == 1
        # Modifying the returned list should not affect internal state
        f.clear()
        assert len(builder.findings) == 1

    def test_findings_setter(self):
        builder = FindingBuilder(source_tool="test")
        builder.findings = [{"test": "value"}]
        assert len(builder._findings) == 1
        assert builder.findings[0]["test"] == "value"

    def test_clear(self):
        builder = FindingBuilder(source_tool="test")
        builder.add("XSS", "HIGH", "/api", {})
        assert len(builder.findings) == 1
        builder.clear()
        assert builder.findings == []

    def test_emit_callback_called(self):
        callback = None
        results = []

        def emit(engagement_id, finding, tool_name):
            results.append((engagement_id, finding, tool_name))

        builder = FindingBuilder(source_tool="nuclei", engagement_id="eng-1", emit_finding=emit)
        builder.add("XSS", "HIGH", "/api", {})
        assert len(results) == 1
        assert results[0][0] == "eng-1"
        assert results[0][2] == "nuclei"

    def test_emit_callback_exception_does_not_propagate(self):
        def broken_emit(engagement_id, finding, tool_name):
            raise RuntimeError("broken")

        builder = FindingBuilder(source_tool="test", engagement_id="eng-1", emit_finding=broken_emit)
        # Should not raise
        finding = builder.add("XSS", "HIGH", "/api", {})
        assert finding["type"] == "XSS"
