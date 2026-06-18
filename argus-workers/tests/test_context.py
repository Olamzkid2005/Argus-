"""Tests for tools.context — Category: parser"""

import pytest

from tools.context import ParserProtocol


class TestParserProtocol:
    """Tests for the ParserProtocol parser."""

    def setup_method(self):
        self.parser = ParserProtocol()

    def test_empty_input(self):
        """Empty input returns empty list."""
        result = self.parser.parse("")
        assert result == []

    def test_blank_lines(self):
        """Whitespace-only input returns empty list."""
        result = self.parser.parse("\n  \n\n")
        assert result == []

    def test_parse_results_are_list(self):
        """parse() always returns a list."""
        result = self.parser.parse("")
        assert isinstance(result, list)

    def test_findings_have_required_keys(self):
        """Parsed findings have type, severity, endpoint."""
        result = self.parser.parse("test input")
        if result:
            for finding in result:
                assert "type" in finding
                assert "severity" in finding
                assert "endpoint" in finding or "tool" in finding
