"""Tests for parsers.parsers.testssl — Category: parser"""


from parsers.parsers.testssl import TestsslParser


class TestTestsslParser:
    """Tests for the TestsslParser parser."""

    def setup_method(self):
        self.parser = TestsslParser()

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
        result = self.parser.parse("{\"host\": \"example.com\", \"port\": 443, \"severity\": \"HIGH\", \"id\": \"HEARTBLEED\", \"finding\": \"Vulnerable to Heartbleed\"}\n{\"host\": \"example.com\", \"port\": 443, \"severity\": \"MEDIUM\", \"id\": \"TLS_VERSION\", \"finding\": \"TLS 1.2 supported\"}\n")
        assert isinstance(result, list)
        assert len(result) > 0, "Sample input should produce findings"
        assert "type" in result[0], "Finding should have a type"
        assert "severity" in result[0], "Finding should have a severity"
        assert "endpoint" in result[0], "Finding should have an endpoint"

