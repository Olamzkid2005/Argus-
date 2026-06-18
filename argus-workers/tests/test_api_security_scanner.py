"""
Tests for APISecurityScanner (AsyncTool pattern).

Uses mocked ``httpx.AsyncClient`` to test scanner logic without live HTTP.
Follows the same pattern as ``test_web_scanner.py`` and ``test_ai_vuln_scanner.py``.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from tool_core.base import ToolContext
from tool_core.result import ToolStatus
from tools.api_security_scanner import APISecurityScanner

# ── Helpers ─────────────────────────────────────────────────────────────


def _mock_async_response(
    status_code: int = 200,
    text: str = "",
    headers: dict | None = None,
) -> Mock:
    """Build a mocked httpx.Response."""
    resp = Mock(status_code=status_code)
    resp.text = text
    resp.headers = headers or {}
    return resp


def _run_async(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ── Construction & State ────────────────────────────────────────────────


class TestAPISecurityScannerConstruction:
    """Scanner initialises with correct defaults."""

    def test_tool_name(self):
        assert APISecurityScanner.tool_name == "api_security_scanner"

    def test_inherits_async_tool(self):
        from tool_core.base import AsyncTool

        assert issubclass(APISecurityScanner, AsyncTool)

    def test_defaults(self):
        scanner = APISecurityScanner()
        assert scanner.timeout == 15
        assert len(scanner.AUTH_HEADER_VARIANTS) == 9
        assert len(scanner.MASS_ASSIGNMENT_PAYLOADS) == 5

    def test_custom_timeout(self):
        scanner = APISecurityScanner(timeout=30)
        assert scanner.timeout == 30


# ── _check_deps ─────────────────────────────────────────────────────────


class TestCheckDeps:
    """_check_deps raises if httpx is not available."""

    def test_raises_when_missing(self):
        with patch("tools.api_security_scanner.HAS_HTTPX", False):
            with pytest.raises(RuntimeError, match="httpx library is required"):
                APISecurityScanner()


# ── _validate_external_url (pure logic) ─────────────────────────────────


class TestValidateExternalUrl:
    """_validate_external_url blocks internal/private URLs."""

    def test_valid_https(self):
        # Should not raise
        APISecurityScanner._validate_external_url("https://example.com")

    def test_valid_http(self):
        APISecurityScanner._validate_external_url("http://example.com")

    def test_raises_on_empty_hostname(self):
        with pytest.raises(ValueError, match="Could not parse hostname"):
            APISecurityScanner._validate_external_url("")

    def test_blocks_localhost(self):
        with pytest.raises(ValueError, match="Blocked localhost"):
            APISecurityScanner._validate_external_url("http://localhost:8080/api")

    def test_blocks_127_dot_0_dot_0_dot_1(self):
        with pytest.raises(ValueError, match="Blocked internal IP|Blocked localhost"):
            APISecurityScanner._validate_external_url("http://127.0.0.1/api")

    def test_blocks_private_ip(self):
        with pytest.raises(ValueError, match="Blocked internal IP"):
            APISecurityScanner._validate_external_url("http://10.0.0.5/api")

    def test_blocks_cloud_metadata(self):
        """169.254.169.254 is link-local so caught by IP check."""
        with pytest.raises(
            ValueError, match="Blocked internal IP|Blocked cloud metadata"
        ):
            APISecurityScanner._validate_external_url("http://169.254.169.254/")

    def test_blocks_gcp_metadata(self):
        with pytest.raises(ValueError, match="Blocked GCP metadata"):
            APISecurityScanner._validate_external_url(
                "http://instance.metadata.google.internal/"
            )

    def test_blocks_hostname_resolving_to_private(self):
        """M-v4-04: DNS-based SSRF prevention."""
        import socket

        def _fake_getaddrinfo(host, port, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

        with patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo):
            with pytest.raises(ValueError, match="resolves to private IP"):
                APISecurityScanner._validate_external_url(
                    "http://internal-service.example.com/api"
                )

    def test_dns_failure_does_not_block(self):
        """DNS resolution failure should not raise."""
        import socket

        with patch("socket.getaddrinfo", side_effect=socket.gaierror("no address")):
            # Should not raise — let the caller handle connection errors
            APISecurityScanner._validate_external_url(
                "http://unreachable-host.example.com"
            )


# ── _try_replace_id (pure regex logic) ──────────────────────────────────


class TestTryReplaceId:
    """_try_replace_id replaces ID-like path segments."""

    def test_replaces_numeric_id(self):
        result = APISecurityScanner._try_replace_id("/api/users/123")
        assert result == "/api/users/456"

    def test_replaces_different_numeric_id(self):
        result = APISecurityScanner._try_replace_id("/api/users/456")
        assert result == "/api/users/999"

    def test_replaces_hex_id(self):
        result = APISecurityScanner._try_replace_id(
            "/api/items/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c"
        )
        # 32-char hex matches the first (8+ hex) pattern → UUID format
        assert "00000000-0000-0000-0000-000000000000" in result

    def test_replaces_uuid(self):
        result = APISecurityScanner._try_replace_id(
            "/api/users/550e8400e29b41d4a716446655440000"
        )
        assert "00000000-0000-0000-0000-000000000000" in result

    def test_returns_none_for_no_id(self):
        result = APISecurityScanner._try_replace_id("/api/users/me")
        assert result is None

    def test_returns_none_for_empty_path(self):
        result = APISecurityScanner._try_replace_id("")
        assert result is None


# ── _test_bola ──────────────────────────────────────────────────────────


class TestBola:
    """_test_bola detects BOLA/IDOR via ID replacement."""

    SCANNER_BASE_URL = "https://api.example.com"

    @pytest.fixture
    def scanner(self):
        return APISecurityScanner()

    def test_detects_confirmed_bola(self, scanner):
        """Similar-sized responses with different IDs = BOLA."""
        orig_body = "data" * 50  # 200 chars
        alt_body = "datx" * 50  # 200 chars (same length, different content)
        orig_resp = _mock_async_response(status_code=200, text=orig_body)
        alt_resp = _mock_async_response(status_code=200, text=alt_body)

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mock_client
                mock_client.get = AsyncMock(side_effect=[orig_resp, alt_resp])

                findings = await scanner._test_bola(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 1
        assert findings[0]["type"] == "API_BOLA"
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["confidence"] == 0.7

    def test_detects_potential_bola(self, scanner):
        """Different status codes (not 404) = MEDIUM BOLA."""
        orig_body = "data" * 50
        orig_resp = _mock_async_response(status_code=200, text=orig_body)
        # Use 500 (not 401/403/404) to reach the elif branch
        alt_resp = _mock_async_response(status_code=500, text="Server Error")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mock_client
                mock_client.get = AsyncMock(side_effect=[orig_resp, alt_resp])

                findings = await scanner._test_bola(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 1
        assert findings[0]["type"] == "API_BOLA"
        assert findings[0]["severity"] == "MEDIUM"
        assert findings[0]["confidence"] == 0.5

    def test_skips_when_auth_fails(self, scanner):
        """401/403 on either request → skip."""
        orig_resp = _mock_async_response(status_code=401, text="Unauthorized")
        alt_resp = _mock_async_response(status_code=200, text="{}")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.get.side_effect = [orig_resp, alt_resp]

                findings = await scanner._test_bola(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_skips_non_id_endpoint(self, scanner):
        """Endpoints without ID-like segments are skipped."""

        async def run():
            with patch("httpx.AsyncClient"):
                findings = await scanner._test_bola(
                    self.SCANNER_BASE_URL,
                    ["/api/users/me"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_handles_request_error(self, scanner):
        """RequestError on either request → skip."""

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.get.side_effect = httpx_connection_error()

                findings = await scanner._test_bola(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_with_builder_routes_through(self, scanner):
        """When _builder is set, findings route through builder.add()."""
        from tool_core.finding_builder import FindingBuilder

        scanner._builder = FindingBuilder(source_tool="api_security_scanner")
        orig_body = "data" * 50
        alt_body = "datx" * 50
        orig_resp = _mock_async_response(status_code=200, text=orig_body)
        alt_resp = _mock_async_response(status_code=200, text=alt_body)

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_cls.return_value.__aenter__.return_value = mock_client
                mock_client.get = AsyncMock(side_effect=[orig_resp, alt_resp])

                findings = await scanner._test_bola(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            assert len(findings) == 1
            assert len(scanner._builder.findings) == 1
            assert scanner._builder.findings[0]["source_tool"] == "api_security_scanner"

        _run_async(run())


# ── _test_mass_assignment ───────────────────────────────────────────────


class TestMassAssignment:
    """_test_mass_assignment detects reflected privilege fields."""

    SCANNER_BASE_URL = "https://api.example.com"

    @pytest.fixture
    def scanner(self):
        return APISecurityScanner()

    def test_detects_reflected_field(self, scanner):
        """Payload key/value reflected in response = finding."""
        resp = _mock_async_response(
            status_code=200,
            text='{"role": "admin", "message": "updated"}',
        )

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_mass_assignment(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) >= 1
        assert findings[0]["type"] == "API_MASS_ASSIGNMENT"
        assert findings[0]["severity"] == "HIGH"

    def test_skips_on_auth_error(self, scanner):
        """401/403/404/405/501/5xx responses are skipped."""
        resp = _mock_async_response(status_code=403, text="Forbidden")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_mass_assignment(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_skips_non_reflected_payload(self, scanner):
        """Fields not reflected in response → no finding."""
        resp = _mock_async_response(
            status_code=200,
            text='{"message": "ok"}',
        )

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_mass_assignment(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_handles_request_error(self, scanner):
        """RequestError → skip that request."""

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.side_effect = httpx_connection_error()

                findings = await scanner._test_mass_assignment(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_with_builder_routes_through(self, scanner):
        from tool_core.finding_builder import FindingBuilder

        scanner._builder = FindingBuilder(source_tool="api_security_scanner")
        resp = _mock_async_response(
            status_code=200,
            text='{"role": "admin"}',
        )

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_mass_assignment(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                    {},
                )
            assert len(findings) >= 1
            assert len(scanner._builder.findings) >= 1
            assert scanner._builder.findings[0]["source_tool"] == "api_security_scanner"

        _run_async(run())


# ── _test_auth_bypass ───────────────────────────────────────────────────


class TestAuthBypass:
    """_test_auth_bypass detects endpoints accessible without auth."""

    SCANNER_BASE_URL = "https://api.example.com"

    @pytest.fixture
    def scanner(self):
        return APISecurityScanner()

    def test_detects_bypass(self, scanner):
        """200 returned without auth → CRITICAL finding."""
        resp = _mock_async_response(status_code=200, text='{"data": "sensitive"}')

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_auth_bypass(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                )
            return findings

        findings = _run_async(run())
        # 9 auth variants × 3 methods (GET, POST, PUT) = 27 calls for 1 endpoint
        # All return 200 → 27 findings? No — only the ones that return 200.
        # With our mock, all 27 return 200.
        assert len(findings) == 27
        assert all(f["type"] == "API_AUTH_BYPASS" for f in findings)
        assert all(f["severity"] == "CRITICAL" for f in findings)

    def test_skips_public_endpoints(self, scanner):
        """Public endpoint patterns are skipped."""
        resp = _mock_async_response(status_code=200, text="ok")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_auth_bypass(
                    self.SCANNER_BASE_URL,
                    ["/health", "/api/health"],
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_skips_non_200_responses(self, scanner):
        """401/403/etc responses → no finding."""
        resp = _mock_async_response(status_code=401, text="Unauthorized")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_auth_bypass(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_handles_request_error(self, scanner):
        """RequestError → skip that request."""

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.side_effect = httpx_connection_error()

                findings = await scanner._test_auth_bypass(
                    self.SCANNER_BASE_URL,
                    ["/api/users/123"],
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_with_builder_routes_through(self, scanner):
        from tool_core.finding_builder import FindingBuilder

        scanner._builder = FindingBuilder(source_tool="api_security_scanner")
        resp = _mock_async_response(status_code=200, text="ok")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_auth_bypass(
                    self.SCANNER_BASE_URL,
                    ["/api/admin"],
                )
            assert len(findings) >= 1
            assert len(scanner._builder.findings) >= 1
            assert scanner._builder.findings[0]["source_tool"] == "api_security_scanner"

        _run_async(run())


# ── _test_api_rate_limiting ─────────────────────────────────────────────


class TestRateLimiting:
    """_test_api_rate_limiting checks for 429 responses."""

    SCANNER_BASE_URL = "https://api.example.com"

    @pytest.fixture
    def scanner(self):
        return APISecurityScanner()

    def test_detects_rate_limited(self, scanner):
        """429 detected → API_RATE_LIMITED finding."""
        resp_ok = _mock_async_response(status_code=200, text="ok")
        resp_429 = _mock_async_response(status_code=429, text="Too Many Requests")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                # First chunk: some 200, then a 429
                mock_client.get.side_effect = [resp_ok, resp_429] + [resp_ok] * 48

                findings = await scanner._test_api_rate_limiting(
                    self.SCANNER_BASE_URL,
                    ["/api/login"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 1
        assert findings[0]["type"] == "API_RATE_LIMITED"
        assert findings[0]["severity"] == "INFO"

    def test_detects_no_rate_limit(self, scanner):
        """All 200s → API_NO_RATE_LIMIT finding."""
        resp_ok = _mock_async_response(status_code=200, text="ok")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.get.return_value = resp_ok

                findings = await scanner._test_api_rate_limiting(
                    self.SCANNER_BASE_URL,
                    ["/api/login"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 1
        assert findings[0]["type"] == "API_NO_RATE_LIMIT"
        assert findings[0]["severity"] == "MEDIUM"

    def test_inconclusive_all_failed(self, scanner):
        """All requests failed → API_RATE_LIMIT_INCONCLUSIVE."""

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.get.side_effect = httpx_connection_error()

                findings = await scanner._test_api_rate_limiting(
                    self.SCANNER_BASE_URL,
                    ["/api/login"],
                    {},
                )
            return findings

        findings = _run_async(run())
        assert len(findings) == 1
        assert findings[0]["type"] == "API_RATE_LIMIT_INCONCLUSIVE"

    def test_skips_non_auth_endpoints(self, scanner):
        """Only auth-related endpoints are tested."""

        async def run():
            findings = await scanner._test_api_rate_limiting(
                self.SCANNER_BASE_URL,
                ["/api/users/123", "/api/items"],
                {},
            )
            return findings

        findings = _run_async(run())
        assert len(findings) == 0

    def test_with_builder_routes_through(self, scanner):
        from tool_core.finding_builder import FindingBuilder

        scanner._builder = FindingBuilder(source_tool="api_security_scanner")
        resp_ok = _mock_async_response(status_code=200, text="ok")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.get.return_value = resp_ok

                findings = await scanner._test_api_rate_limiting(
                    self.SCANNER_BASE_URL,
                    ["/api/login"],
                    {},
                )
            assert len(findings) == 1
            assert len(scanner._builder.findings) == 1
            assert scanner._builder.findings[0]["source_tool"] == "api_security_scanner"

        _run_async(run())


# ── scan() flow ─────────────────────────────────────────────────────────


class TestScan:
    """scan() orchestrates all check methods."""

    @pytest.fixture
    def scanner(self):
        return APISecurityScanner()

    def test_returns_empty_when_feature_disabled(self, scanner):
        """Feature flag off → empty list."""

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=False):
                findings = await scanner.scan(
                    "https://api.example.com",
                    ["/api/users/123"],
                )
            return findings

        findings = _run_async(run())
        assert findings == []

    def test_runs_discovery_when_no_endpoints(self, scanner):
        """Empty endpoints → runs discovery."""

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=True):
                with patch.object(scanner, "_validate_external_url"):
                    with patch.object(
                        scanner,
                        "discover_endpoints",
                        return_value=["/api/users/123"],
                    ):
                        with patch.object(scanner, "_test_bola", return_value=[]):
                            with patch.object(
                                scanner, "_test_mass_assignment", return_value=[]
                            ):
                                with patch.object(
                                    scanner, "_test_auth_bypass", return_value=[]
                                ):
                                    with patch.object(
                                        scanner,
                                        "_test_api_rate_limiting",
                                        return_value=[],
                                    ):
                                        findings = await scanner.scan(
                                            "https://api.example.com",
                                            [],
                                        )
            return findings

        findings = _run_async(run())
        assert findings == []

    def test_discovery_returns_empty_returns_empty(self, scanner):
        """No endpoints discovered → empty result."""

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=True):
                with patch.object(scanner, "_validate_external_url"):
                    with patch.object(scanner, "discover_endpoints", return_value=[]):
                        findings = await scanner.scan(
                            "https://api.example.com",
                            [],
                        )
            return findings

        findings = _run_async(run())
        assert findings == []

    def test_runs_all_checks_with_endpoints(self, scanner):
        """Provided endpoints run through all 4 checks."""

        async def _make_bola(*a, **kw):
            return [scanner._add_finding("API_BOLA", "HIGH", "url", {}, 0.7)]

        async def _make_ma(*a, **kw):
            return [scanner._add_finding("API_MASS_ASSIGNMENT", "HIGH", "url", {}, 0.6)]

        async def _make_ab(*a, **kw):
            return [scanner._add_finding("API_AUTH_BYPASS", "CRITICAL", "url", {}, 0.5)]

        async def _make_rl(*a, **kw):
            return [scanner._add_finding("API_NO_RATE_LIMIT", "MEDIUM", "url", {}, 0.6)]

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=True):
                with patch.object(scanner, "_validate_external_url"):
                    with patch.object(scanner, "_test_bola", side_effect=_make_bola):
                        with patch.object(
                            scanner, "_test_mass_assignment", side_effect=_make_ma
                        ):
                            with patch.object(
                                scanner, "_test_auth_bypass", side_effect=_make_ab
                            ):
                                with patch.object(
                                    scanner,
                                    "_test_api_rate_limiting",
                                    side_effect=_make_rl,
                                ):
                                    findings = await scanner.scan(
                                        "https://api.example.com",
                                        ["/api/users/123"],
                                    )
            return findings

        findings = _run_async(run())
        assert len(findings) == 4
        assert any(f["type"] == "API_BOLA" for f in findings)

    def test_scan_delegates_to_async_execute(self, scanner):
        """scan() shim delegates to async_execute()."""

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=True):
                with patch.object(scanner, "_validate_external_url"):
                    with patch.object(scanner, "_test_bola"):
                        with patch.object(scanner, "_test_mass_assignment"):
                            with patch.object(scanner, "_test_auth_bypass"):
                                with patch.object(scanner, "_test_api_rate_limiting"):
                                    findings = await scanner.scan(
                                        "https://api.example.com",
                                        ["/api/users/123"],
                                    )
            return findings

        findings = _run_async(run())
        assert findings == []  # shim returns result.findings from async_execute


# ── async_execute(ctx) ──────────────────────────────────────────────────


class TestAsyncExecute:
    """async_execute() is the AsyncTool entry point."""

    @pytest.fixture
    def scanner(self):
        return APISecurityScanner()

    def _mocked_run(self, scanner, discovery_return=None):
        """Context manager that mocks check methods + discovery for isolated testing."""
        discovery = discovery_return or ["/api/test"]
        return patch.multiple(
            scanner,
            _validate_external_url=Mock(),
            discover_endpoints=AsyncMock(return_value=discovery),
            _test_bola=AsyncMock(return_value=[]),
            _test_mass_assignment=AsyncMock(return_value=[]),
            _test_auth_bypass=AsyncMock(return_value=[]),
            _test_api_rate_limiting=AsyncMock(return_value=[]),
        )

    def test_returns_unified_tool_result(self, scanner):
        """async_execute returns UnifiedToolResult."""
        ctx = ToolContext(target="https://api.example.com")

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=False):
                result = await scanner.async_execute(ctx)
            return result

        result = _run_async(run())
        assert result.tool_name == "api_security_scanner"
        assert result.status == ToolStatus.SUCCESS
        assert result.target == "https://api.example.com"
        assert result.finished_at is not None

    def test_sets_builder_on_instance(self, scanner):
        """async_execute creates FindingBuilder on self._builder."""
        from tool_core.finding_builder import FindingBuilder

        ctx = ToolContext(target="https://api.example.com")

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=False):
                await scanner.async_execute(ctx)
            assert scanner._builder is not None
            assert isinstance(scanner._builder, FindingBuilder)
            assert scanner._builder.source_tool == "api_security_scanner"

        _run_async(run())

    def test_propagates_engagement_id(self, scanner):
        """Engagement ID flows to builder."""
        ctx = ToolContext(target="https://api.example.com", engagement_id="eng-42")

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=False):
                await scanner.async_execute(ctx)
            assert scanner._builder.engagement_id == "eng-42"

        _run_async(run())

    def test_maps_timeout(self, scanner):
        """ToolContext timeout overwrites scanner timeout."""
        ctx = ToolContext(target="https://api.example.com", timeout=88)

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=False):
                await scanner.async_execute(ctx)
            assert scanner.timeout == 88

        _run_async(run())

    def test_returns_findings_from_scan(self, scanner):
        """Findings produced by check methods appear in the result."""

        async def _make_bola(*a, **kw):
            return [scanner._add_finding("API_BOLA", "HIGH", "url", {}, 0.7)]

        ctx = ToolContext(target="https://api.example.com")

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=True):
                with patch.object(scanner, "_validate_external_url"):
                    with patch.object(
                        scanner, "discover_endpoints", return_value=["/api/test"]
                    ):
                        with patch.object(
                            scanner, "_test_bola", side_effect=_make_bola
                        ):
                            with patch.object(
                                scanner, "_test_mass_assignment", return_value=[]
                            ):
                                with patch.object(
                                    scanner, "_test_auth_bypass", return_value=[]
                                ):
                                    with patch.object(
                                        scanner,
                                        "_test_api_rate_limiting",
                                        return_value=[],
                                    ):
                                        result = await scanner.async_execute(ctx)
            return result

        result = _run_async(run())
        assert len(result.findings) >= 1
        assert result.findings[0]["type"] == "API_BOLA"

    def test_passes_endpoints_empty_by_default_to_trigger_discovery(self, scanner):
        """Without explicit endpoints, discovery is triggered."""
        ctx = ToolContext(target="https://api.example.com")

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=True):
                with patch.object(scanner, "_validate_external_url"):
                    with patch.object(
                        scanner, "discover_endpoints", return_value=["/api/test"]
                    ) as mock_discovery:
                        with patch.object(scanner, "_test_bola", return_value=[]):
                            with patch.object(
                                scanner, "_test_mass_assignment", return_value=[]
                            ):
                                with patch.object(
                                    scanner, "_test_auth_bypass", return_value=[]
                                ):
                                    with patch.object(
                                        scanner,
                                        "_test_api_rate_limiting",
                                        return_value=[],
                                    ):
                                        await scanner.async_execute(ctx)
                                        mock_discovery.assert_called_once()

        _run_async(run())

    def test_accepts_explicit_endpoints(self, scanner):
        """Callers can provide explicit endpoints to avoid relying on discovery."""
        ctx = ToolContext(target="https://api.example.com")
        explicit_endpoints = ["/api/users/123", "/api/login", "/api/admin"]

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=True):
                with patch.object(scanner, "_validate_external_url"):
                    with patch.object(scanner, "discover_endpoints") as mock_discovery:
                        with patch.object(scanner, "_test_bola") as mock_bola:
                            with patch.object(scanner, "_test_mass_assignment"):
                                with patch.object(scanner, "_test_auth_bypass"):
                                    with patch.object(
                                        scanner,
                                        "_test_api_rate_limiting",
                                        return_value=[],
                                    ):
                                        await scanner.async_execute(
                                            ctx, endpoints=explicit_endpoints
                                        )
                                        # Discovery should NOT be called
                                        mock_discovery.assert_not_called()
                                        # Endpoints passed to check methods
                                        args, _ = mock_bola.call_args
                                        assert args[1] == explicit_endpoints

        _run_async(run())

    def test_explicit_endpoints_empty_list_passed_verbatim(self, scanner):
        """When explicitly passing endpoints=[], discovery is triggered (same as default)."""
        ctx = ToolContext(target="https://api.example.com")

        async def run():
            with patch("tools.api_security_scanner.is_enabled", return_value=True):
                with patch.object(scanner, "_validate_external_url"):
                    with patch.object(
                        scanner, "discover_endpoints", return_value=["/api/test"]
                    ) as mock_discovery:
                        with patch.object(scanner, "_test_bola", return_value=[]):
                            with patch.object(
                                scanner, "_test_mass_assignment", return_value=[]
                            ):
                                with patch.object(
                                    scanner, "_test_auth_bypass", return_value=[]
                                ):
                                    with patch.object(
                                        scanner,
                                        "_test_api_rate_limiting",
                                        return_value=[],
                                    ):
                                        await scanner.async_execute(ctx, endpoints=[])
                                        # [] triggers discovery same as default
                                        mock_discovery.assert_called_once()

        _run_async(run())


# ── _extract_openapi_paths (pure logic) ─────────────────────────────────


class TestExtractOpenapiPaths:
    """_extract_openapi_paths parses OpenAPI JSON specs."""

    def test_extracts_paths_from_valid_json(self):
        spec = '{"paths": {"/users": {"get": {}}, "/items": {"post": {}}}}'
        paths = APISecurityScanner._extract_openapi_paths(spec, "application/json")
        assert "/users" in paths
        assert "/items" in paths
        assert len(paths) == 2

    def test_returns_empty_for_invalid_json(self):
        paths = APISecurityScanner._extract_openapi_paths("not json", "text/plain")
        assert paths == []

    def test_returns_empty_for_empty_body(self):
        paths = APISecurityScanner._extract_openapi_paths("", "application/json")
        assert paths == []

    def test_accepts_body_starting_with_brace_even_without_json_content_type(self):
        spec = '{"paths": {"/api/test": {"get": {}}}}'
        paths = APISecurityScanner._extract_openapi_paths(spec, "text/plain")
        assert "/api/test" in paths


# ── _extract_api_from_html (pure logic) ─────────────────────────────────


class TestExtractApiFromHtml:
    """_extract_api_from_html extracts API endpoints from HTML/JS."""

    def test_extracts_fetch_calls(self):
        html = '<script>fetch("/api/users/123")</script>'
        urls = APISecurityScanner._extract_api_from_html(html, "https://example.com")
        assert "/api/users/123" in urls

    def test_extracts_axios_calls(self):
        html = '<script>axios.get("/api/items")</script>'
        urls = APISecurityScanner._extract_api_from_html(html, "https://example.com")
        assert "/api/items" in urls

    def test_extracts_ajax_calls(self):
        html = '<script>$.ajax("/api/data")</script>'
        urls = APISecurityScanner._extract_api_from_html(html, "https://example.com")
        assert "/api/data" in urls

    def test_extracts_full_urls_same_domain(self):
        html = '<script>fetch("https://example.com/api/users")</script>'
        urls = APISecurityScanner._extract_api_from_html(html, "https://example.com")
        assert "/api/users" in urls

    def test_skips_cross_domain_urls(self):
        html = '<script>fetch("https://other.com/api/data")</script>'
        urls = APISecurityScanner._extract_api_from_html(html, "https://example.com")
        assert "/api/data" not in urls
        assert len(urls) == 0

    def test_returns_empty_for_no_matches(self):
        html = "<html><body>Hello</body></html>"
        urls = APISecurityScanner._extract_api_from_html(html, "https://example.com")
        assert urls == []


# ── Finding schema compliance ───────────────────────────────────────────


class TestFindingSchema:
    """All findings conform to expected schema."""

    REQUIRED_KEYS = {
        "type",
        "severity",
        "endpoint",
        "evidence",
        "confidence",
        "source_tool",
    }
    VALID_SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_bola_findings_have_required_schema(self):
        """BOLA findings have all required keys."""
        scanner = APISecurityScanner()
        orig_body = "data" * 50
        alt_body = "datx" * 50
        orig_resp = _mock_async_response(status_code=200, text=orig_body)
        alt_resp = _mock_async_response(status_code=200, text=alt_body)

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.get.side_effect = [orig_resp, alt_resp]

                findings = await scanner._test_bola(
                    "https://api.example.com",
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        self._check_schema(findings)

    def test_mass_assignment_findings_have_required_schema(self):
        scanner = APISecurityScanner()
        resp = _mock_async_response(
            status_code=200,
            text='{"role": "admin"}',
        )

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_mass_assignment(
                    "https://api.example.com",
                    ["/api/users/123"],
                    {},
                )
            return findings

        findings = _run_async(run())
        self._check_schema(findings)

    def test_auth_bypass_findings_have_required_schema(self):
        scanner = APISecurityScanner()
        resp = _mock_async_response(status_code=200, text="ok")

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = mock_cls.return_value.__aenter__.return_value
                mock_client.request.return_value = resp

                findings = await scanner._test_auth_bypass(
                    "https://api.example.com",
                    ["/api/admin"],
                )
            return findings

        findings = _run_async(run())
        self._check_schema(findings)

    def _check_schema(self, findings):
        for f in findings:
            missing = self.REQUIRED_KEYS - set(f.keys())
            assert not missing, f"Finding {f.get('type', '?')} missing keys: {missing}"
            assert f["source_tool"] == "api_security_scanner"
            assert 0.0 <= f["confidence"] <= 1.0
            assert f["severity"] in self.VALID_SEVERITIES, (
                f"Invalid severity '{f['severity']}' for {f['type']}"
            )
            assert f["endpoint"], f"Finding {f['type']} has empty endpoint"


# ── Private helper: httpx connection error ──────────────────────────────


def httpx_connection_error():
    """Return an exception that matches httpx.RequestError."""
    try:
        import httpx

        return httpx.RequestError("Connection refused")
    except ImportError:
        return Exception("Connection refused")
