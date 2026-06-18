"""Tests for parsers.parsers.httpx — Category: parser"""

import pytest

from parsers.parsers.httpx import HttpxParser


class TestHttpxParser:
    """Tests for the HttpxParser parser."""

    def setup_method(self):
        self.parser = HttpxParser()

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
        result = self.parser.parse("{\"url\": \"https://example.com\", \"status_code\": 200, \"title\": \"Example\"}\n{\"url\": \"https://example.com/admin\", \"status_code\": 403, \"title\": \"Forbidden\"}\n")

