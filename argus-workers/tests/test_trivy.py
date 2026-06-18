"""Tests for parsers.parsers.trivy — Category: parser"""

import pytest

from parsers.parsers.trivy import TrivyParser


class TestTrivyParser:
    """Tests for the TrivyParser parser."""

    def setup_method(self):
        self.parser = TrivyParser()

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
        result = self.parser.parse("{\"Target\": \"test-image:latest\", \"Vulnerabilities\": [{\"VulnerabilityID\": \"CVE-2024-1234\", \"PkgName\": \"test-pkg\", \"Severity\": \"HIGH\", \"Title\": \"Test vuln\"}]}\n")

