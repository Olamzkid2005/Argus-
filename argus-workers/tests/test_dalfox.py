"""Tests for parsers.parsers.dalfox — Category: parser"""

import pytest

from parsers.parsers.dalfox import DalfoxParser


class TestDalfoxParser:
    """Tests for the DalfoxParser parser."""

    def setup_method(self):
        self.parser = DalfoxParser()

    def test_empty_input(self):
        """Empty input returns empty list."""
        result = self.parser.parse("")
        assert result == []
    def test_malformed_input(self):
        """Malformed input returns empty list."""
        result = self.parser.parse("NOT A VALID INPUT")
        assert isinstance(result, list)
        assert len(result) == 0
    def test_parse_results_are_list(self):
        """parse() always returns a list."""
        result = self.parser.parse("")
        assert isinstance(result, list)

    def test_parses_valid_input(self):
        """Parses realistic sample input."""
        result = self.parser.parse("{\"URL\": \"https://example.com/?q=test\", \"Severity\": \"Medium\", \"Type\": \"ReflectedXSS\", \"Payload\": \"<script>alert(1)</script>\"}\n")
        assert isinstance(result, list)
        assert len(result) > 0, "Sample input should produce findings"
        assert "type" in result[0], "Finding should have a type"
        assert "severity" in result[0], "Finding should have a severity"
        assert "endpoint" in result[0], "Finding should have an endpoint"


