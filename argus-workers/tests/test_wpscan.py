"""Tests for parsers.parsers.wpscan — Category: parser"""

import pytest

from parsers.parsers.wpscan import WpscanParser


class TestWpscanParser:
    """Tests for the WpscanParser parser."""

    def setup_method(self):
        self.parser = WpscanParser()

    def test_empty_input(self):
        """Empty input returns empty list."""
        result = self.parser.parse("")
        assert result == []

    def test_malformed_input(self):
        """Malformed input returns empty list."""
        result = self.parser.parse("NOT A VALID INPUT")
        assert isinstance(result, list)
        assert len(result) == 0
    def test_blank_lines(self):
        """Whitespace-only input returns empty list."""
        result = self.parser.parse("\n  \n\n")
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
        result = self.parser.parse("{\"target_url\": \"https://example.com\", \"interesting_findings\": [{\"type\": \"db_backup\", \"url\": \"https://example.com/wp-content/backup.zip\", \"to_s\": \"DB backup exposed\"}], \"version\": {\"number\": \"5.0\", \"vulnerabilities\": [{\"title\": \"XSS\", \"cvss\": {\"severity\": \"high\"}}]}}\n")
        assert isinstance(result, list)
        assert len(result) > 0, "Sample input should produce findings"
        assert "type" in result[0], "Finding should have a type"
        assert "severity" in result[0], "Finding should have a severity"
        assert "endpoint" in result[0], "Finding should have an endpoint"

