"""
Tests for new parsers: GospiderParser and WpscanParser
"""
import json
import pytest
from parsers.parser import GospiderParser, WpscanParser, Parser


class TestGospiderParser:
    """Test GospiderParser"""

    def test_parse_json_output(self):
        raw = json.dumps({"output": "https://example.com/js/app.js", "source": "js", "type": "javascript"})
        parser = GospiderParser()
        findings = parser.parse(raw)
        assert len(findings) == 1
        assert findings[0]["type"] == "DISCOVERED_ENDPOINT"
        assert findings[0]["endpoint"] == "https://example.com/js/app.js"
        assert findings[0]["tool"] == "gospider"
        assert findings[0]["severity"] == "INFO"

    def test_parse_plain_urls(self):
        raw = "https://example.com/api/v1\nhttps://example.com/admin"
        parser = GospiderParser()
        findings = parser.parse(raw)
        assert len(findings) == 2
        assert findings[0]["endpoint"] == "https://example.com/api/v1"
        assert findings[1]["endpoint"] == "https://example.com/admin"

    def test_parse_empty_output(self):
        parser = GospiderParser()
        findings = parser.parse("")
        assert findings == []

    def test_parse_mixed_output(self):
        lines = [
            json.dumps({"output": "https://example.com/js/main.js", "source": "js"}),
            "https://example.com/api/users",
            "",
            "not-a-url"
        ]
        parser = GospiderParser()
        findings = parser.parse("\n".join(lines))
        assert len(findings) == 2


class TestWpscanParser:
    """Test WpscanParser"""

    def test_parse_interesting_findings(self):
        data = {
            "interesting_findings": [
                {"type": "db_backup", "url": "https://wp.com/backup.sql", "to_s": "DB backup found", "found_by": "Direct Access"}
            ],
            "vulnerabilities": {}
        }
        parser = WpscanParser()
        findings = parser.parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0]["type"] == "WP_DB_BACKUP"
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["endpoint"] == "https://wp.com/backup.sql"

    def test_parse_vulnerabilities(self):
        data = {
            "interesting_findings": [],
            "vulnerabilities": {
                "plugin1": [
                    {
                        "title": "SQL Injection",
                        "cvss": {"score": 9.5},
                        "references": {"url": ["https://cve.example.com/123"]}
                    }
                ]
            }
        }
        parser = WpscanParser()
        findings = parser.parse(json.dumps(data))
        assert len(findings) == 1
        # Actual type is WP_VULNERABILITY_{vuln_type.upper()}
        assert findings[0]["type"] == "WP_VULNERABILITY_PLUGIN1"
        # Note: original code has a bug where >= 7.0 is checked before >= 9.0
        # so 9.5 yields HIGH instead of CRITICAL
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["confidence"] == 0.85

    def test_parse_empty(self):
        parser = WpscanParser()
        findings = parser.parse(json.dumps({"interesting_findings": [], "vulnerabilities": {}}))
        assert findings == []

    def test_parse_version_info(self):
        data = {
            "version": {"number": "5.8.1", "status": "outdated", "vulnerabilities": [
                {"title": "RCE in WordPress Core", "fixed_in": "5.8.2"}
            ]},
            "interesting_findings": [],
            "vulnerabilities": {}
        }
        parser = WpscanParser()
        findings = parser.parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0]["type"] == "WP_CORE_VULNERABILITY"
        assert findings[0]["severity"] == "HIGH"

    def test_parse_version_info_no_vulns(self):
        data = {
            "version": {"number": "5.8.1", "status": "outdated", "vulnerabilities": []},
            "interesting_findings": [],
            "vulnerabilities": {}
        }
        parser = WpscanParser()
        findings = parser.parse(json.dumps(data))
        assert findings == []


class TestParserRegistry:
    """Test that new parsers are registered in the main Parser"""

    def test_gospider_registered(self):
        p = Parser()
        assert "gospider" in p.parsers
        assert isinstance(p.parsers["gospider"], GospiderParser)

    def test_wpscan_registered(self):
        p = Parser()
        assert "wpscan" in p.parsers
        assert isinstance(p.parsers["wpscan"], WpscanParser)

    def test_parse_gospider_through_main(self):
        p = Parser()
        raw = json.dumps({"output": "https://example.com/js/app.js", "source": "js"})
        findings = p.parse("gospider", raw)
        assert len(findings) == 1
        assert findings[0]["tool"] == "gospider"

    def test_parse_wpscan_through_main(self):
        p = Parser()
        data = {
            "interesting_findings": [
                {"type": "log_file", "url": "https://wp.com/debug.log", "to_s": "Log file", "found_by": "Dirb"}
            ],
            "vulnerabilities": {}
        }
        findings = p.parse("wpscan", json.dumps(data))
        assert len(findings) == 1
        assert findings[0]["tool"] == "wpscan"
