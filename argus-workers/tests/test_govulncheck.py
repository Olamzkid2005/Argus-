"""Tests for parsers.parsers.govulncheck — Category: parser"""


from parsers.parsers.govulncheck import GovulncheckParser


class TestGovulncheckParser:
    """Tests for the GovulncheckParser parser."""

    def setup_method(self):
        self.parser = GovulncheckParser()

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

    def test_parse_results_are_list(self):
        """parse() always returns a list."""
        result = self.parser.parse("")
        assert isinstance(result, list)

    def test_parses_valid_input(self):
        """Parses realistic sample input."""
        result = self.parser.parse("{\"Vulns\": [{\"OSV\": \"CVE-2024-1234\", \"PkgPath\": \"stdlib\", \"Symbol\": \"ReadFile\", \"CurrentVersion\": \"1.21.0\", \"FixedVersion\": \"1.21.1\"}]}\n")
        assert isinstance(result, list)
        assert len(result) > 0, "Sample input should produce findings"
        assert "type" in result[0], "Finding should have a type"
        assert "severity" in result[0], "Finding should have a severity"
        assert "endpoint" in result[0], "Finding should have an endpoint"


