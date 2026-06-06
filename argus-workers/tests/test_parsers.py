"""Unit tests for all tool output parsers."""

import json

import pytest

from tool_core.parser.parsers import nuclei, nmap, semgrep, gitleaks, whatweb, nikto, sqlmap, generic
from tool_core.parser.dispatcher import dispatch


class TestNucleiParser:
    def test_valid_json_line(self):
        line = json.dumps({
            "info": {"name": "SQL Injection", "severity": "high",
                     "classification": {"cwe": ["CWE-89"], "cve": ["CVE-2021-1234"]}},
            "matched-at": "https://example.com/api",
            "template-id": "sqli-test",
        })
        findings = nuclei.parse(line)
        assert len(findings) == 1
        assert findings[0].title == "SQL Injection"
        assert findings[0].severity == 3
        assert findings[0].cwe == "CWE-89"
        assert findings[0].cve == "CVE-2021-1234"
        assert findings[0].tool == "nuclei"

    def test_multiple_lines(self):
        lines = [
            json.dumps({"info": {"name": "XSS", "severity": "medium"}, "matched-at": "/x"}),
            json.dumps({"info": {"name": "IDOR", "severity": "high"}, "matched-at": "/y"}),
        ]
        findings = nuclei.parse("\n".join(lines))
        assert len(findings) == 2

    def test_skips_empty_lines(self):
        output = "\n\n" + json.dumps({"info": {"name": "Test", "severity": "low"}, "matched-at": "/x"}) + "\n\n"
        findings = nuclei.parse(output)
        assert len(findings) == 1

    def test_handles_invalid_json(self):
        output = "not json\n" + json.dumps({"info": {"name": "Test", "severity": "low"}, "matched-at": "/x"})
        findings = nuclei.parse(output)
        assert len(findings) == 1

    def test_cwe_cve_as_list(self):
        """cwe/cve can be lists in nuclei JSON; parser must join them."""
        line = json.dumps({
            "info": {"name": "Test", "severity": "medium",
                     "classification": {"cwe": ["CWE-79", "CWE-80"], "cve": ["CVE-2021-1", "CVE-2021-2"]}},
            "matched-at": "/x",
        })
        findings = nuclei.parse(line)
        assert findings[0].cwe == "CWE-79,CWE-80"
        assert findings[0].cve == "CVE-2021-1,CVE-2021-2"

    def test_empty_output(self):
        assert nuclei.parse("") == []


class TestNmapParser:
    SAMPLE_XML = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <address addr="192.168.1.1" addrtype="ipv4"/>
    <hostnames><hostname name="router.local" type="PTR"/></hostnames>
    <ports>
      <port portid="80" protocol="tcp">
        <state state="open" reason="syn-ack"/>
        <service name="http" product="Apache" version="2.4.41"/>
      </port>
      <port portid="22" protocol="tcp">
        <state state="open" reason="syn-ack"/>
        <service name="ssh" product="OpenSSH" version="8.0"/>
      </port>
      <port portid="443" protocol="tcp">
        <state state="filtered" reason="no-response"/>
        <service name="https"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

    def test_parses_open_ports(self):
        findings = nmap.parse(self.SAMPLE_XML)
        assert len(findings) == 2  # 80 and 22 open; 443 filtered
        assert findings[0].evidence[0]["port"] == "80"
        assert findings[1].evidence[0]["port"] == "22"

    def test_service_info(self):
        findings = nmap.parse(self.SAMPLE_XML)
        assert "Apache" in findings[0].description
        assert findings[0].tool == "nmap"

    def test_empty_output(self):
        assert nmap.parse("") == []

    def test_malformed_xml(self):
        assert nmap.parse("not xml") == []


class TestSemgrepParser:
    SAMPLE_JSON = json.dumps({
        "results": [{
            "check_id": "python.flask.security.xss",
            "path": "app.py",
            "start": {"line": 42},
            "extra": {
                "severity": "high",
                "message": "XSS vulnerability",
                "lines": "return render_template(...)",
                "metadata": {
                    "cwe": ["CWE-79", "CWE-80"],
                    "owasp": "A7",
                },
            },
        }]
    })

    def test_parses_results(self):
        findings = semgrep.parse(self.SAMPLE_JSON)
        assert len(findings) == 1
        assert findings[0].title == "python.flask.security.xss"
        assert findings[0].severity == 3

    def test_cwe_as_list(self):
        findings = semgrep.parse(self.SAMPLE_JSON)
        assert findings[0].cwe == "CWE-79,CWE-80"

    def test_cwe_as_string(self):
        data = json.loads(self.SAMPLE_JSON)
        data["results"][0]["extra"]["metadata"]["cwe"] = "CWE-79"
        findings = semgrep.parse(json.dumps(data))
        assert findings[0].cwe == "CWE-79"

    def test_cwe_missing(self):
        data = json.loads(self.SAMPLE_JSON)
        del data["results"][0]["extra"]["metadata"]["cwe"]
        findings = semgrep.parse(json.dumps(data))
        assert findings[0].cwe == ""

    def test_empty_results(self):
        findings = semgrep.parse(json.dumps({"results": []}))
        assert findings == []

    def test_empty_output(self):
        assert semgrep.parse("") == []


class TestGitleaksParser:
    SAMPLE_JSON = json.dumps([{
        "RuleID": "aws-key",
        "Severity": "high",
        "Description": "AWS Access Key",
        "File": "config.py",
        "StartLine": 10,
        "Commit": "abc123",
        "Author": "dev",
        "Secret": "AKIA123456",
        "Match": "AKIA...",
    }])

    def test_parses_leaks(self):
        findings = gitleaks.parse(self.SAMPLE_JSON)
        assert len(findings) == 1
        assert findings[0].title == "aws-key"
        assert findings[0].severity == 3
        assert findings[0].tool == "gitleaks"

    def test_single_object(self):
        data = json.loads(self.SAMPLE_JSON)[0]
        findings = gitleaks.parse(json.dumps(data))
        assert len(findings) == 1

    def test_empty_output(self):
        assert gitleaks.parse("") == []

    def test_malformed_json(self):
        assert gitleaks.parse("not json") == []


class TestWhatwebParser:
    SAMPLE_JSON = json.dumps([{
        "url": "https://example.com",
        "WordPress": {"version": "5.8"},
        "PHP": {"version": "7.4"},
    }])

    def test_parses_technologies(self):
        findings = whatweb.parse(self.SAMPLE_JSON)
        assert len(findings) == 1
        assert "WordPress" in findings[0].title
        assert "PHP" in findings[0].title

    def test_multiple_entries(self):
        findings = whatweb.parse(
            json.dumps({"url": "https://a.com", "Nginx": {}}) + "\n" +
            json.dumps({"url": "https://b.com", "Apache": {}})
        )
        assert len(findings) == 2

    def test_empty_output(self):
        assert whatweb.parse("") == []


class TestNiktoParser:
    def test_parse_json(self):
        output = json.dumps([{
            "msg": "High vulnerability found",
            "OSVDB": "1234",
            "url": "https://example.com/test",
        }])
        findings = nikto.parse(output)
        assert len(findings) == 1
        assert findings[0].tool == "nikto"

    def test_parse_csv(self):
        output = "host,80,1234,GET,/test,description here\n"
        findings = nikto.parse(output)
        assert len(findings) == 1

    def test_parse_text(self):
        output = "- Some finding text here for testing\n+ Another finding\n"
        findings = nikto.parse(output)
        assert len(findings) == 2

    def test_empty_output(self):
        assert nikto.parse("") == []

    def test_infer_severity_word_boundary(self):
        """'high' substring in 'higher' or 'highly' should not match \bhigh\b."""
        from tool_core.parser.parsers.nikto import _infer_severity
        assert _infer_severity("higher education") == 2  # default medium, not 3
        assert _infer_severity("highlighting info") == 0  # 'info' matches \binfo\b
        assert _infer_severity("this is high risk") == 3  # word boundary match


class TestSqlmapParser:
    SAMPLE_JSON = json.dumps({
        "data": [{
            "url": "https://example.com/page",
            "parameters": {
                "id": {
                    "title": "boolean blind SQL injection",
                    "payload": "1 AND 1=1",
                }
            },
        }]
    })

    def test_parse_json(self):
        findings = sqlmap.parse(self.SAMPLE_JSON)
        assert len(findings) == 1
        assert findings[0].severity == 4
        assert findings[0].confidence == 5
        assert findings[0].tool == "sqlmap"

    def test_parse_text(self):
        output = "sqlmap identified the following injection point: https://example.com?id=1"
        findings = sqlmap.parse(output)
        assert len(findings) == 1
        assert findings[0].severity == 4

    def test_empty_output(self):
        assert sqlmap.parse("") == []


class TestGenericParser:
    def test_parse_json(self):
        output = json.dumps({"title": "custom finding", "severity": "high", "tool": "custom"})
        findings = generic.parse(output)
        assert len(findings) == 1
        assert findings[0].title == "custom finding"

    def test_parse_raw_text(self):
        findings = generic.parse("some random output\nwith URLs https://example.com")
        assert len(findings) >= 1

    def test_empty_output(self):
        assert generic.parse("") == []


class TestDispatch:
    def test_dispatches_to_correct_parser(self):
        output = json.dumps({
            "info": {"name": "SQLI", "severity": "high",
                     "classification": {"cwe": ["CWE-89"], "cve": []}},
            "matched-at": "/x",
        })
        findings = dispatch("nuclei", output)
        assert len(findings) == 1
        assert findings[0].tool == "nuclei"

    def test_falls_back_to_generic(self):
        findings = dispatch("unknown_tool", "some random text")
        assert len(findings) >= 1

    def test_handles_malformed_input(self):
        findings = dispatch("nuclei", "")
        assert findings == []
