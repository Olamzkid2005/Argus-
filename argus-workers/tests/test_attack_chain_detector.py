"""Tests for tools.correlation.attack_chain_detector — Category: function"""


from tools.correlation.attack_chain_detector import (
    _build_dependency_graph,
    _endpoint_host,
    detect_attack_chains,
)


class TestEndpointHost:
    """Tests for the _endpoint_host function."""

    def test_returns_hostname(self):
        """Extracts hostname from URL."""
        result = _endpoint_host("https://example.com/path")
        assert isinstance(result, str)
        assert "example.com" in result

    def test_empty_endpoint(self):
        """Empty string returns empty."""
        result = _endpoint_host("")
        assert result == ""


class TestBuildDependencyGraph:
    """Tests for the _build_dependency_graph function."""

    def test_empty_findings(self):
        """Empty findings return empty graph."""
        result = _build_dependency_graph([])
        assert isinstance(result, dict)


class TestDetectAttackChains:
    """Tests for the detect_attack_chains function."""

    def test_empty_findings(self):
        """Empty findings return empty list."""
        result = detect_attack_chains([])
        assert isinstance(result, list)
        assert result == []
