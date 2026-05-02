"""
Comprehensive tests for 11 new parsers, AuthManager, BrowserScanner, and SBOM generator.

Each parser gets three tests:
  1. Valid output → correct finding schema
  2. Malformed output → empty list, no raise
  3. Empty string → empty list
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parsers.parsers.dalfox import DalfoxParser
from parsers.parsers.arjun import ArjunParser
from parsers.parsers.naabu import NaabuParser
from parsers.parsers.nikto import NiktoParser
from parsers.parsers.amass import AmassParser
from parsers.parsers.subfinder import SubfinderParser
from parsers.parsers.whatweb import WhatwebParser
from parsers.parsers.jwt_tool import JwtToolParser
from parsers.parsers.commix import CommixParser
from parsers.parsers.testssl import TestsslParser
from parsers.parsers.alterx import AlterxParser

# ── 11 New Parsers ──

class TestDalfoxParser(unittest.TestCase):
    def test_parse_xss_finding(self):
        raw = '{"type":"G","data":{"url":"http://t.com/s?q=x","param":"q","payload":"<script>alert(1)</script>"}}\n'
        findings = DalfoxParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "XSS")
        self.assertEqual(findings[0]["tool"], "dalfox")
        self.assertIn("payload", findings[0]["evidence"])

    def test_parse_empty(self):
        self.assertEqual(DalfoxParser().parse(""), [])

    def test_parse_malformed(self):
        self.assertEqual(DalfoxParser().parse("not json\n{bad}"), [])

    def test_parse_multiple_lines(self):
        raw = (
            '{"type":"G","data":{"url":"http://t.com/a","param":"q","payload":"<s>1</s>"}}\n'
            '{"type":"G","data":{"url":"http://t.com/b","param":"r","payload":"<s>2</s>"}}\n'
        )
        findings = DalfoxParser().parse(raw)
        self.assertEqual(len(findings), 2)


class TestArjunParser(unittest.TestCase):
    def test_parse_params(self):
        raw = json.dumps({"https://t.com/api": ["id", "name", "role"]})
        findings = ArjunParser().parse(raw)
        self.assertGreaterEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "PARAMETER_DISCOVERY")
        self.assertEqual(findings[0]["tool"], "arjun")

    def test_parse_empty(self):
        self.assertEqual(ArjunParser().parse(""), [])

    def test_parse_malformed(self):
        self.assertEqual(ArjunParser().parse("{bad json}"), [])


class TestNaabuParser(unittest.TestCase):
    def test_parse_port(self):
        raw = '{"host":"10.0.0.1","port":443,"protocol":"tcp"}\n'
        findings = NaabuParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "OPEN_PORT")
        self.assertIn("443", findings[0]["endpoint"])
        self.assertEqual(findings[0]["tool"], "naabu")

    def test_parse_empty(self):
        self.assertEqual(NaabuParser().parse(""), [])

    def test_parse_malformed(self):
        self.assertEqual(NaabuParser().parse("bad\n"), [])


class TestNiktoParser(unittest.TestCase):
    def test_parse_vuln(self):
        raw = json.dumps([{"OSVDB": "123", "url": "http://t.com/", "msg": "Critical issue found"}])
        findings = NiktoParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "WEB_SERVER_VULNERABILITY")
        self.assertEqual(findings[0]["tool"], "nikto")

    def test_parse_empty(self):
        self.assertEqual(NiktoParser().parse(""), [])

    def test_parse_malformed(self):
        self.assertEqual(NiktoParser().parse("not json"), [])


class TestAmassParser(unittest.TestCase):
    def test_parse_subdomain(self):
        raw = '{"name":"sub.test.com","addresses":[{"ip":"1.2.3.4"}],"tag":"dns"}\n'
        findings = AmassParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "SUBDOMAIN_DISCOVERY")
        self.assertEqual(findings[0]["endpoint"], "sub.test.com")
        self.assertEqual(findings[0]["tool"], "amass")

    def test_parse_empty(self):
        self.assertEqual(AmassParser().parse(""), [])

    def test_parse_malformed(self):
        self.assertEqual(AmassParser().parse("bad\n"), [])


class TestSubfinderParser(unittest.TestCase):
    def test_parse_subdomains(self):
        raw = "sub1.test.com\nsub2.test.com\n"
        findings = SubfinderParser().parse(raw)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["type"], "SUBDOMAIN_DISCOVERY")
        self.assertEqual(findings[0]["tool"], "subfinder")

    def test_parse_empty(self):
        self.assertEqual(SubfinderParser().parse(""), [])

    def test_parse_ignores_http_prefix(self):
        raw = "https://example.com\nsub.test.com\n"
        findings = SubfinderParser().parse(raw)
        self.assertEqual(len(findings), 1)


class TestWhatwebParser(unittest.TestCase):
    def test_parse_json_array(self):
        raw = json.dumps([{"url": "http://t.com", "WordPress": "6.0", "jQuery": "3.6"}])
        findings = WhatwebParser().parse(raw)
        self.assertGreaterEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "TECHNOLOGY_DETECTED")
        self.assertIn("plugins", findings[0]["evidence"])
        self.assertEqual(findings[0]["tool"], "whatweb")

    def test_parse_empty(self):
        self.assertEqual(WhatwebParser().parse(""), [])

    def test_parse_json_lines(self):
        raw = '{"url":"http://t.com","Apache":"2.4"}\n{"url":"http://t2.com","nginx":"1.20"}\n'
        findings = WhatwebParser().parse(raw)
        self.assertEqual(len(findings), 2)


class TestJwtToolParser(unittest.TestCase):
    def test_parse_vulnerable_line(self):
        raw = "[+] This token is vulnerable to algorithm confusion!\n[-] Nothing here\n"
        findings = JwtToolParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "JWT_VULNERABILITY")
        self.assertEqual(findings[0]["severity"], "HIGH")
        self.assertEqual(findings[0]["tool"], "jwt_tool")

    def test_parse_warning_line(self):
        raw = "[!] Warning: Signature not verified\n"
        findings = JwtToolParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "MEDIUM")

    def test_parse_empty(self):
        self.assertEqual(JwtToolParser().parse(""), [])

    def test_parse_no_matches(self):
        self.assertEqual(JwtToolParser().parse("[-] Nothing found\n[-] All good\n"), [])


class TestCommixParser(unittest.TestCase):
    def test_parse_confirmed(self):
        raw = "some output\n[*] Setting the OS shell...\nmore output\n"
        findings = CommixParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "COMMAND_INJECTION")
        self.assertEqual(findings[0]["severity"], "CRITICAL")
        self.assertEqual(findings[0]["tool"], "commix")

    def test_parse_not_confirmed(self):
        raw = "some output\nno injection detected\n"
        findings = CommixParser().parse(raw)
        self.assertEqual(len(findings), 0)

    def test_parse_empty(self):
        self.assertEqual(CommixParser().parse(""), [])

    def test_parse_pseudo_shell(self):
        raw = "[*] Setting the pseudo terminal...\n"
        findings = CommixParser().parse(raw)
        self.assertEqual(len(findings), 1)


class TestTestsslParser(unittest.TestCase):
    def test_parse_vuln(self):
        raw = '{"host":"example.com","port":443,"severity":"HIGH","id":"SSL_TEST","finding":"Weak cipher"}\n'
        findings = TestsslParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "TLS_VULNERABILITY")
        self.assertEqual(findings[0]["severity"], "HIGH")
        self.assertEqual(findings[0]["tool"], "testssl")

    def test_parse_info_severity(self):
        raw = '{"host":"example.com","port":443,"severity":"INFO","id":"CERT_TEST","finding":"Cert info"}\n'
        findings = TestsslParser().parse(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "INFO")

    def test_parse_empty(self):
        self.assertEqual(TestsslParser().parse(""), [])

    def test_parse_malformed(self):
        self.assertEqual(TestsslParser().parse("bad\n"), [])


class TestAlterxParser(unittest.TestCase):
    def test_parse_subdomains(self):
        raw = "dev.test.com\nadmin.test.com\nstaging.test.com\n"
        findings = AlterxParser().parse(raw)
        self.assertEqual(len(findings), 3)
        self.assertEqual(findings[0]["type"], "SUBDOMAIN_DISCOVERY")
        self.assertEqual(findings[0]["tool"], "alterx")

    def test_parse_empty(self):
        self.assertEqual(AlterxParser().parse(""), [])

    def test_parse_ignores_http(self):
        raw = "https://test.com\napi.test.com\n"
        findings = AlterxParser().parse(raw)
        self.assertEqual(len(findings), 1)


# ── AuthManager ──

class TestAuthManager(unittest.TestCase):
    def test_cookie_auth(self):
        from tools.auth_manager import AuthManager, AuthConfig
        am = AuthManager(AuthConfig(cookie="sessionid=abc123"))
        session = am.authenticate("https://example.com")
        self.assertEqual(session.cookies.get("sessionid"), "abc123")

    def test_token_auth(self):
        from tools.auth_manager import AuthManager, AuthConfig
        am = AuthManager(AuthConfig(token="tok_xyz"))
        session = am.authenticate("https://example.com")
        self.assertEqual(session.headers.get("Authorization"), "Bearer tok_xyz")

    def test_empty_config(self):
        from tools.auth_manager import AuthManager
        am = AuthManager(None)
        session = am.authenticate("https://example.com")
        self.assertIsNotNone(session)

    def test_api_key_auth(self):
        from tools.auth_manager import AuthManager, AuthConfig
        am = AuthManager(AuthConfig(token="key_abc", token_header="X-API-Key"))
        session = am.authenticate("https://example.com")
        self.assertIn("key_abc", session.headers.get("X-API-Key", ""))

    def test_attach_to_session(self):
        from tools.auth_manager import AuthManager, AuthConfig
        import requests
        am = AuthManager(AuthConfig(cookie="sess=val"))
        sess = requests.Session()
        am.attach_to_session(sess)
        self.assertEqual(sess.cookies.get("sess"), "val")


# ── BrowserScanner (mocked subprocess) ──

class TestBrowserScanner(unittest.TestCase):
    @patch("subprocess.run")
    def test_scan_returns_findings(self, mock_run):
        from tools.browser_scanner import scan
        expected = [{"type": "SPA_FRAMEWORK_DETECTED", "severity": "INFO", "endpoint": "https://t.com", "tool": "browser_scanner"}]
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(expected)
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        findings = scan("https://t.com")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "SPA_FRAMEWORK_DETECTED")
        self.assertEqual(findings[0]["tool"], "browser_scanner")

    @patch("subprocess.run")
    def test_scan_nonzero_exit(self, mock_run):
        from tools.browser_scanner import scan
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"
        mock_run.return_value = mock_result

        findings = scan("https://t.com")
        self.assertEqual(len(findings), 0)

    @patch("subprocess.run")
    def test_scan_bad_json(self, mock_run):
        from tools.browser_scanner import scan
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"
        mock_run.return_value = mock_result

        findings = scan("https://t.com")
        self.assertEqual(len(findings), 0)

    @patch("subprocess.run")
    def test_scan_timeout(self, mock_run):
        from tools.browser_scanner import scan
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 5)
        findings = scan("https://t.com", timeout=5)
        self.assertEqual(len(findings), 0)

    def test_is_spa_target(self):
        from tools.browser_scanner import is_spa_target
        self.assertTrue(is_spa_target(["React"]))
        self.assertTrue(is_spa_target(["Vue.js", "Django"]))
        self.assertTrue(is_spa_target(["Next.js"]))
        self.assertFalse(is_spa_target(["PHP", "WordPress"]))
        self.assertFalse(is_spa_target([]))


# ── SBOM Generator ──

class TestSBOMGenerator(unittest.TestCase):
    def test_generates_cyclonedx(self):
        from tools.sbom_generator import generate_sbom_from_findings
        findings = [
            {"type": "DEPENDENCY_VULNERABILITY", "severity": "HIGH",
             "evidence": {"package": "lodash", "version": "4.17.20", "fix_version": "4.17.21",
                          "vulnerable_versions": "< 4.17.21", "cve": "CVE-2024-1234"}},
        ]
        sbom = generate_sbom_from_findings("e-1", findings)
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertEqual(sbom["specVersion"], "1.5")
        self.assertEqual(len(sbom["components"]), 1)
        self.assertEqual(len(sbom["vulnerabilities"]), 1)

    def test_skips_non_dependency(self):
        from tools.sbom_generator import generate_sbom_from_findings
        findings = [
            {"type": "XSS", "severity": "HIGH", "evidence": {}},
        ]
        sbom = generate_sbom_from_findings("e-1", findings)
        self.assertEqual(sbom, {})

    def test_handles_multiple_cves(self):
        from tools.sbom_generator import generate_sbom_from_findings
        findings = [
            {"type": "DEPENDENCY_VULNERABILITY", "severity": "CRITICAL",
             "evidence": {"package": "requests", "version": "2.28.0",
                          "cves": ["CVE-2024-5678", "CVE-2024-9012"]}},
        ]
        sbom = generate_sbom_from_findings("e-1", findings)
        self.assertEqual(len(sbom["vulnerabilities"][0]["advisories"]), 2)

    def test_deduplicates_same_package(self):
        from tools.sbom_generator import generate_sbom_from_findings
        findings = [
            {"type": "DEPENDENCY_VULNERABILITY", "severity": "HIGH",
             "evidence": {"package": "lodash", "version": "4.17.20", "cve": "CVE-2024-1"}},
            {"type": "DEPENDENCY_VULNERABILITY", "severity": "HIGH",
             "evidence": {"package": "lodash", "version": "4.17.20", "cve": "CVE-2024-2"}},
        ]
        sbom = generate_sbom_from_findings("e-1", findings)
        self.assertEqual(len(sbom["components"]), 1)
        self.assertEqual(len(sbom["vulnerabilities"]), 2)

    def test_empty_findings(self):
        from tools.sbom_generator import generate_sbom_from_findings
        self.assertEqual(generate_sbom_from_findings("e-1", []), {})


if __name__ == "__main__":
    unittest.main()
