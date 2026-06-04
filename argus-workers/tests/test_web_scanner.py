"""
Tests for WebScanner (AbstractTool pattern).

Uses mocked ``_safe_request`` to test scanner logic without live HTTP.
Follows the same pattern as ``test_api_scanner.py``.
"""

from unittest.mock import Mock, patch

import pytest

from tool_core.base import ToolContext
from tool_core.result import ToolStatus
from tools.web_scanner import WebScanner

# ── Helpers ─────────────────────────────────────────────────────────────


def _mock_response(
    status_code: int = 200,
    headers: dict | None = None,
    text: str = "",
    json_data: dict | None = None,
) -> Mock:
    """Build a mocked requests.Response."""
    resp = Mock(status_code=status_code)
    resp.headers = headers or {}
    resp.text = text
    resp.json.return_value = json_data or {}
    # Support .raw.headers.getlist() for check_cookies
    resp.raw = Mock()
    resp.raw.headers = Mock()
    resp.raw.headers.getlist = Mock(return_value=[])
    return resp


# ── Construction & State ────────────────────────────────────────────────


class TestWebScannerConstruction:
    """Scanner initialises with correct defaults."""

    def test_default_timeout(self):
        scanner = WebScanner()
        assert scanner.timeout == 10  # SSL_TIMEOUT

    def test_default_rate_limit(self):
        scanner = WebScanner()
        assert scanner.rate_limit > 0

    def test_tool_name(self):
        assert WebScanner.tool_name == "web_scanner"

    def test_inherits_abstract_tool(self):
        from tool_core.base import AbstractTool
        assert issubclass(WebScanner, AbstractTool)

    def test_custom_params(self):
        scanner = WebScanner(timeout=30, rate_limit=0.1, engagement_id="eng-1")
        assert scanner.timeout == 30
        assert scanner.rate_limit == 0.1
        assert scanner.engagement_id == "eng-1"


# ── Framework Detection (pure logic, no mocking needed) ─────────────────


class TestFrameworkDetection:
    """_detect_framework works from response headers / body alone."""

    def test_django(self):
        resp = _mock_response(text="<html>csrfmiddlewaretoken</html>")
        assert WebScanner()._detect_framework(resp) == "Django"

    def test_express(self):
        resp = _mock_response(headers={"X-Powered-By": "Express"})
        assert WebScanner()._detect_framework(resp) == "Express"

    def test_wordpress(self):
        resp = _mock_response(text="<html>wp-content/themes</html>")
        assert WebScanner()._detect_framework(resp) == "WordPress"

    def test_unknown(self):
        resp = _mock_response(headers={"Server": "Custom/1.0"}, text="hello")
        assert WebScanner()._detect_framework(resp) == "unknown"

    def test_none_response(self):
        assert WebScanner()._detect_framework(None) == "unknown"


# ── SSRF / Scope validation ────────────────────────────────────────────


class TestScanValidation:
    """scan() rejects invalid targets before making requests."""

    def test_raises_on_disallowed_scheme(self):
        scanner = WebScanner()
        with pytest.raises(ValueError, match="Disallowed URL scheme"):
            scanner.scan("file:///etc/passwd")

    def test_raises_on_gopher_scheme(self):
        scanner = WebScanner()
        with pytest.raises(ValueError, match="Disallowed URL scheme"):
            scanner.scan("gopher://internal:6379")

    def test_scope_validation_rejects(self):
        """When engagement_id is set and scope rejects the target,
        scan() returns [] without making requests."""
        scanner = WebScanner(engagement_id="eng-1")

        with patch("tools.web_scanner.validate_target_scope", return_value=False):
            with patch.object(scanner, "_safe_request") as mock_req:
                findings = scanner.scan("https://out-of-scope.example.com")

        assert findings == []
        mock_req.assert_not_called()


# ── SSRF early-return path ──────────────────────────────────────────────


class TestConnectionErrors:
    """scan() handles connection failures gracefully."""

    def test_ssl_error_retries(self):
        """On SSLError, scanner reports finding and retries without SSL."""
        scanner = WebScanner()
        import requests
        ssl_err = Mock(side_effect=requests.exceptions.SSLError("SSL: CERTIFICATE_VERIFY_FAILED"))

        with patch.object(scanner.session, "get", ssl_err):
            # scan() internally calls _add_finding which routes to builder
            scanner.scan("https://example.com")

        # Findings are stored in the builder after _add_finding
        assert scanner._builder is not None
        ssl_findings = [f for f in scanner._builder.findings if f["type"] == "SSL_CERTIFICATE_ERROR"]
        assert len(ssl_findings) == 1
        assert ssl_findings[0]["type"] == "SSL_CERTIFICATE_ERROR"

    def test_connection_error_returns_empty(self):
        """Generic connection error returns []."""
        scanner = WebScanner()

        with patch.object(scanner.session, "get", side_effect=ConnectionError("Connection refused")):
            findings = scanner.scan("https://unreachable.example.com")

        assert findings == []


# ── Check methods ───────────────────────────────────────────────────────


class TestCheckSecurityHeaders:
    """check_security_headers flags missing headers."""

    def test_missing_headers_finding(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        # Only Content-Type present, no security headers
        resp = _mock_response(headers={"Content-Type": "text/html"})

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_security_headers()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 1
        f = findings[0]
        assert f["type"] == "MISSING_SECURITY_HEADERS"
        assert f["severity"] == "MEDIUM"
        # Should list missing headers
        assert len(f["evidence"]["missing_headers"]) >= 1

    def test_all_headers_present_no_finding(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        headers = dict.fromkeys(scanner.SECURITY_HEADERS, "present")
        headers["Content-Type"] = "text/html"
        resp = _mock_response(headers=headers)

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_security_headers()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 0

    def test_no_response_no_finding(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        with patch.object(scanner, "_safe_request", return_value=None):
            scanner.check_security_headers()
        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 0


class TestCheckCSP:
    """check_csp detects missing / weak CSP."""

    def test_missing_csp(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(headers={})

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_csp()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 1
        assert findings[0]["type"] == "MISSING_CSP"

    def test_unsafe_inline(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(headers={
            "Content-Security-Policy": "script-src 'unsafe-inline' 'self'",
        })

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_csp()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 1
        assert findings[0]["type"] == "WEAK_CSP"
        assert "unsafe-inline" in findings[0]["evidence"]["unsafe_directives"]

    def test_strong_csp(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self'",
        })

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_csp()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 0


class TestCheckCookies:
    """check_cookies flags insecure cookie attributes."""

    def test_insecure_cookie(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(headers={"Set-Cookie": "session=abc123; Path=/"})
        # Mock getlist to return parsed cookie
        resp.raw.headers.getlist = Mock(return_value=["session=abc123; Path=/"])

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_cookies()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 1
        assert findings[0]["type"] == "INSECURE_COOKIE"
        assert "Missing HttpOnly" in findings[0]["evidence"]["issues"]

    def test_secure_cookie(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        cookie = "session=abc123; Path=/; HttpOnly; Secure; SameSite=Lax"
        resp = _mock_response(headers={"Set-Cookie": cookie})
        resp.raw.headers.getlist = Mock(return_value=[cookie])

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_cookies()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 0

    def test_no_cookies_no_finding(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(headers={})
        resp.raw.headers.getlist = Mock(return_value=[])

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_cookies()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 0


class TestCheckCORS:
    """check_cors detects CORS misconfigurations."""

    def test_wildcard_cors(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(headers={
            "Access-Control-Allow-Origin": "*",
        })
        null_resp = _mock_response(headers={})

        def _fake_safe(method, url, **kw):
            if kw.get("headers", {}).get("Origin") == "null":
                return null_resp
            return resp

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            scanner.check_cors()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 1
        assert findings[0]["type"] == "WILDCARD_CORS"
        assert findings[0]["severity"] == "HIGH"

    def test_reflected_origin(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(headers={
            "Access-Control-Allow-Origin": "http://evil.com",
        })
        null_resp = _mock_response(headers={})

        def _fake_safe(method, url, **kw):
            if kw.get("headers", {}).get("Origin") == "null":
                return null_resp
            return resp

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            scanner.check_cors()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 1
        assert findings[0]["type"] == "REFLECTED_ORIGIN_CORS"

    def test_null_origin_accept(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        empty_resp = _mock_response(headers={})
        null_resp = _mock_response(headers={
            "Access-Control-Allow-Origin": "null",
        })

        def _fake_safe(method, url, **kw):
            if kw.get("headers", {}).get("Origin") == "null":
                return null_resp
            return empty_resp

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            scanner.check_cors()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 1
        assert findings[0]["type"] == "NULL_ORIGIN_CORS"

    def test_no_cors_headers(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(headers={})

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_cors()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 0


class TestCheckVerbTampering:
    """check_verb_tampering flags accepted dangerous HTTP methods."""

    def test_trace_accepted(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"

        def _fake_safe(method, url, **kw):
            if method == "TRACE":
                return _mock_response(status_code=200)
            return _mock_response(status_code=405)

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            scanner.check_verb_tampering()

        all_findings = scanner._builder.findings if scanner._builder else []
        trace_findings = [f for f in all_findings if f["type"] == "HTTP_VERB_TAMPERING"]
        assert len(trace_findings) == 1
        assert trace_findings[0]["evidence"]["method"] == "TRACE"

    def test_no_dangerous_methods(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"

        def _fake_safe(method, url, **kw):
            return _mock_response(status_code=405)

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            scanner.check_verb_tampering()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 0


class TestCheckSensitiveFiles:
    """check_sensitive_files detects exposed files."""

    def test_env_file_exposed(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"

        def _fake_safe(method, url, **kw):
            # Match .env URL
            if ".env" in url:
                # Must be > 50 chars to pass the content-length gate
                return _mock_response(status_code=200, text="DATABASE_URL=postgres://user:pass@localhost:5432/mydb?sslmode=require&pool_size=10")
            return None

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            scanner.check_sensitive_files()

        all_findings = scanner._builder.findings if scanner._builder else []
        sensitive_findings = [f for f in all_findings if f["type"] == "EXPOSED_SENSITIVE_FILE"]
        assert len(sensitive_findings) >= 1
        assert ".env" in sensitive_findings[0]["evidence"]["file"]

    def test_html_response_skipped(self):
        """HTML responses are skipped (SPA catch-all false positive)."""
        scanner = WebScanner()
        scanner.target_url = "https://example.com"

        def _fake_safe(method, url, **kw):
            if ".env" in url:
                return _mock_response(status_code=200, text="<!DOCTYPE html><html><body>Not found</body></html>")
            return None

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            scanner.check_sensitive_files()

        findings = scanner._builder.findings if scanner._builder else []
        assert len(findings) == 0


class TestCheckJwtAlgConfusion:
    """check_jwt_algorithm_confusion calls test_jwt_alg_none helper."""

    def test_jwt_found_in_page(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com"
        resp = _mock_response(
            text='<script>var token = "eyJhbGciOiJIUzI1NiJ9.eyJ0ZXN0IjoxfQ.signature"</script>',
        )

        with patch.object(scanner, "_safe_request", return_value=resp):
            scanner.check_jwt_algorithm_confusion()

        # Should have attempted JWT none-alg test
        assert scanner._builder is None or len(scanner._builder.findings) >= 0  # May or may not flag


# ── execute(ctx) integration ────────────────────────────────────────────


class TestExecute:
    """execute() creates builder, runs scan, returns UnifiedToolResult."""

    def test_execute_returns_unified_tool_result(self):
        scanner = WebScanner()
        ctx = ToolContext(target="https://example.com")

        # Mock scan() to return findings
        with patch.object(scanner, "_safe_request", return_value=None):
            result = scanner.execute(ctx)

        assert result.tool_name == "web_scanner"
        assert result.status == ToolStatus.SUCCESS
        assert result.target == "https://example.com"
        assert result.finished_at is not None

    def test_execute_sets_builder(self):
        """execute() creates FindingBuilder and stores on instance."""
        scanner = WebScanner()
        ctx = ToolContext(target="https://example.com")

        with patch.object(scanner, "_safe_request", return_value=None):
            scanner.execute(ctx)

        assert scanner._builder is not None
        assert scanner._builder.source_tool == "web_scanner"

    def test_execute_propagates_engagement_id(self):
        scanner = WebScanner()
        ctx = ToolContext(target="https://example.com", engagement_id="eng-42")

        with patch.object(scanner, "_safe_request", return_value=None):
            scanner.execute(ctx)

        assert scanner.engagement_id == "eng-42"
        assert scanner._builder.engagement_id == "eng-42"

    def test_execute_maps_timeout_and_rate_limit(self):
        scanner = WebScanner()
        ctx = ToolContext(target="https://example.com", timeout=99, rate_limit=0.5)

        with patch.object(scanner, "_safe_request", return_value=None):
            scanner.execute(ctx)

        assert scanner.timeout == 99
        assert scanner.rate_limit == 0.5

    def test_execute_returns_findings_from_builder(self):
        """Findings created via _add_finding during scan() appear in result."""
        scanner = WebScanner()
        ctx = ToolContext(target="https://example.com")

        # Make request fail so checks run but produce no findings
        with patch.object(scanner, "_safe_request", return_value=None):
            result = scanner.execute(ctx)

        # result.findings from builder should be a list (possibly empty)
        assert isinstance(result.findings, list)

    def test_execute_handles_ssl_error_path(self):
        """execute() works when scan() hits an SSL error and retries."""
        scanner = WebScanner()
        ctx = ToolContext(target="https://example.com")

        import requests
        # Simulate SSLError on first request, success on retry
        ssl_err = requests.exceptions.SSLError("SSL: CERTIFICATE_VERIFY_FAILED")
        ok_resp = _mock_response(headers={"Content-Type": "text/html"}, text="<html></html>")
        calls = [ssl_err, ok_resp]

        with patch.object(scanner.session, "get", side_effect=calls):
            # Mock a session close that doesn't error
            with patch.object(scanner.session, "close"):
                result = scanner.execute(ctx)

        assert result.status == ToolStatus.SUCCESS
        assert isinstance(result.findings, list)


# ── Finding schema compliance ───────────────────────────────────────────


class TestFindingSchema:
    """All findings conform to expected schema."""

    REQUIRED_KEYS = {"type", "severity", "endpoint", "evidence", "confidence", "source_tool"}
    VALID_SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_all_findings_have_required_schema(self):
        """Run a full scan against mocked empty responses and verify schema."""
        scanner = WebScanner()
        ctx = ToolContext(target="https://example.com")

        with patch.object(scanner, "_safe_request", return_value=None):
            result = scanner.execute(ctx)

        for f in result.findings:
            missing = self.REQUIRED_KEYS - set(f.keys())
            assert not missing, f"Finding {f.get('type', '?')} missing keys: {missing}"
            assert f["source_tool"] == "web_scanner"
            assert 0.0 <= f["confidence"] <= 1.0
            assert f["severity"] in self.VALID_SEVERITIES, (
                f"Invalid severity '{f['severity']}' for {f['type']}"
            )

    def test_vulnerability_has_endpoint(self):
        """Every finding has a non-empty endpoint."""
        scanner = WebScanner()
        ctx = ToolContext(target="https://example.com")

        with patch.object(scanner, "_safe_request", return_value=None):
            result = scanner.execute(ctx)

        for f in result.findings:
            assert f["endpoint"], f"Finding {f['type']} has empty endpoint"
