"""Tests for parsers.parsers.httpx — the ProjectDiscovery httpx JSON parser."""

import json

from parsers.parsers.httpx import HttpxParser


class TestHttpxParser:
    """A probe line must carry the fingerprint later phases plan against."""

    def test_endpoint_keeps_web_fingerprint(self):
        line = json.dumps(
            {
                "url": "http://127.0.0.1:8080",
                "status_code": 200,
                "content_type": "text/html",
                "title": "Acme Expense Portal",
                "webserver": "Werkzeug/2.0.1 Python/3.7.3",
                "tech": ["Flask:2.0.1", "PHP:7.4.3", "Python:3.7.3"],
            }
        )
        findings = HttpxParser().parse(line)

        endpoint = next(f for f in findings if f["type"] == "HTTP_ENDPOINT")
        assert endpoint["evidence"]["title"] == "Acme Expense Portal"
        assert endpoint["evidence"]["webserver"] == "Werkzeug/2.0.1 Python/3.7.3"
        assert endpoint["evidence"]["tech"] == ["Flask:2.0.1", "PHP:7.4.3", "Python:3.7.3"]

    def test_technology_finding_is_emitted(self):
        line = json.dumps(
            {
                "url": "http://127.0.0.1:8080",
                "status_code": 200,
                "webserver": "Werkzeug/2.0.1",
                "tech": ["Flask:2.0.1"],
            }
        )
        findings = HttpxParser().parse(line)

        tech = [f for f in findings if f["type"] == "TECH_DETECTED"]
        assert len(tech) == 1
        assert tech[0]["endpoint"] == "http://127.0.0.1:8080"
        assert tech[0]["evidence"]["technologies"] == ["Flask:2.0.1"]
        assert tech[0]["evidence"]["webserver"] == "Werkzeug/2.0.1"
        # The fingerprint has to survive into the report text, not only into
        # structured evidence the renderer currently drops.
        assert tech[0]["description"] == "Flask:2.0.1, Werkzeug/2.0.1"

    def test_probe_without_fingerprint_emits_only_the_endpoint(self):
        findings = HttpxParser().parse(json.dumps({"url": "http://127.0.0.1:8080"}))
        assert [f["type"] for f in findings] == ["HTTP_ENDPOINT"]

    def test_comma_separated_tech_string_is_split(self):
        line = json.dumps(
            {"url": "http://x/", "tech": "Flask, PHP:7.4.3", "webserver": "nginx"}
        )
        tech = [f for f in HttpxParser().parse(line) if f["type"] == "TECH_DETECTED"]
        assert tech[0]["evidence"]["technologies"] == ["Flask", "PHP:7.4.3"]

    def test_plain_url_line_still_parses(self):
        findings = HttpxParser().parse("http://127.0.0.1:8080\n")
        assert len(findings) == 1
        assert findings[0]["endpoint"] == "http://127.0.0.1:8080"
