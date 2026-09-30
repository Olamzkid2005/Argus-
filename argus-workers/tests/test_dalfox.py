"""Tests for parsers.parsers.dalfox — Category: parser"""


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

    def test_parses_dalfox_v2_jsonl(self):
        """dalfox v2 puts the URL *string* in `data` and param/payload at the
        top level (`dalfox url --format jsonl`)."""
        raw = (
            '{"type":"V","inject_type":"inHTML-URL","method":"GET",'
            '"data":"http://t.com/reflect?q=%3Cscript%3E","param":"q",'
            '"payload":"<sCripT class=dalfox>alert(1)</sCriPt>",'
            '"cwe":"CWE-79","severity":"High","message_str":"Triggered XSS"}'
        )

        findings = self.parser.parse(raw)

        assert len(findings) == 1
        finding = findings[0]
        assert finding["endpoint"] == "http://t.com/reflect?q=%3Cscript%3E"
        assert finding["severity"] == "HIGH"
        assert finding["confidence"] == 0.95  # type V
        assert finding["title"] == "Verified XSS in parameter 'q'"
        assert finding["evidence"]["payload"].startswith("<sCripT")


