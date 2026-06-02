"""
API Security Scanner

Automated API security testing without requiring an OpenAPI spec.
Tests for:
- BOLA/IDOR (Broken Object Level Authorization)
- Mass assignment vulnerabilities
- Authentication bypass
- Rate limiting

Gated behind ARGUS_FF_API_SCANNER feature flag.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from feature_flags import is_enabled
from tool_core.base import AsyncTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class APISecurityScanner(AsyncTool):
    """Automated API security testing — no OpenAPI spec required."""

    tool_name = "api_security_scanner"

    PUBLIC_ENDPOINT_PATTERNS: list[str] = [
        "/health", "/api/health", "/api/version", "/api/status",
        "/favicon.ico", "/robots.txt", "/api-docs", "/swagger.json",
        "/openapi.json", "/.well-known/",
    ]
    RATE_LIMIT_REQUEST_COUNT: int = 50
    RATE_LIMIT_CONCURRENCY: int = 10
    BOLA_ALT_IDS: list[str] = ["456", "999", "admin", "1"]
    KNOWN_API_PATHS: list[str] = [
        "/api/", "/v1/", "/v2/", "/v3/", "/rest/",
        "/graphql", "/api-docs", "/swagger.json", "/openapi.json",
    ]
    AUTH_HEADER_VARIANTS: list[dict[str, str] | None] = [
        None,
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer invalid"},
        {"Authorization": "Basic "},
        {"Authorization": "Basic Og=="},
        {"X-API-Key": ""},
        {"X-API-Key": "invalid"},
    ]
    MASS_ASSIGNMENT_PAYLOADS: list[dict[str, Any]] = [
        {"role": "admin"},
        {"is_admin": True},
        {"permissions": ["*"]},
        {"admin": True},
        {"access_level": "administrator"},
    ]

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self._builder: FindingBuilder | None = None
        self._check_deps()

    @staticmethod
    def _check_deps() -> None:
        if not HAS_HTTPX:
            raise RuntimeError(
                "httpx library is required. Install with: pip install httpx"
            )

    def _add_finding(
        self,
        finding_type: str,
        severity: str,
        endpoint: str,
        evidence: dict,
        confidence: float = 0.8,
    ) -> dict:
        """Register a finding via ``self._builder``, lazily creating it if needed.

        Returns the finding dict so callers can build a local results list for
        backward compat with direct test calls.

        Matches the ``WebScanner._add_finding`` pattern.
        """
        if self._builder is None:
            self._builder = FindingBuilder(
                source_tool=self.tool_name,
                engagement_id=getattr(self, "engagement_id", ""),
            )
        return self._builder.add(finding_type, severity, endpoint, evidence, confidence)

    @staticmethod
    def _validate_external_url(url: str) -> None:
        """Raise ValueError if the URL resolves to an internal/private host.

        M-v4-04: Performs DNS resolution for hostname-based targets to prevent
        SSRF via DNS names that resolve to private IPs (e.g., internal-db.corp
        resolving to 10.0.0.5).
        """
        hostname = urlparse(url).hostname
        if not hostname:
            raise ValueError(f"Could not parse hostname from URL: {url}")
        # Block internal/reserved IPs and localhost variants
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None  # not an IP literal — check hostname patterns and resolve DNS
        if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast):
            raise ValueError(f"Blocked internal IP: {hostname}")
        blocked_hostnames = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1"}
        hostname_lower = hostname.lower()
        if hostname_lower in blocked_hostnames:
            raise ValueError(f"Blocked localhost address: {hostname}")
        # Block cloud metadata endpoints
        if hostname_lower == "169.254.169.254":
            raise ValueError(f"Blocked cloud metadata endpoint: {hostname}")
        if hostname_lower.endswith(".metadata.google.internal"):
            raise ValueError(f"Blocked GCP metadata endpoint: {hostname}")
        # M-v4-04: DNS resolution check — resolve hostname and validate all
        # resolved IPs against private ranges. This catches DNS rebinding attacks
        # and hostnames that internally resolve to private addresses.
        import socket as _socket
        try:
            addrinfo = _socket.getaddrinfo(hostname, None)
            for _family, _typ, _proto, _cn, sockaddr in addrinfo:
                resolved_ip = sockaddr[0]
                try:
                    addr = ipaddress.ip_address(resolved_ip)
                except ValueError:
                    continue
                if addr.is_private or addr.is_loopback or addr.is_link_local:
                    raise ValueError(
                        f"Blocked hostname {hostname} resolves to private IP {resolved_ip}"
                    )
        except _socket.gaierror:
            pass  # DNS resolution failed — let the caller handle connection errors

    async def scan(
        self,
        base_url: str,
        endpoints: list[str],
        auth_headers: dict[str, str] | None = None,
        builder: FindingBuilder | None = None,
    ) -> list[dict[str, Any]]:
        """
        Run all API security tests.

        Backward-compatible shim that delegates to ``async_execute()``.
        Existing callers that call ``scan()`` directly still work unchanged.

        Args:
            base_url: Base URL of the target API.
            endpoints: List of endpoint paths (e.g. ["/api/users/123", "/api/login"]).
            auth_headers: Deprecated — ``async_execute()`` stores auth_headers on self.
            builder: Deprecated — ``async_execute()`` creates its own ``FindingBuilder``.

        Returns:
            List of finding dicts compatible with VulnerabilityFinding schema.
        """
        self._scan_auth_headers = auth_headers or {}
        ctx = ToolContext(target=base_url)
        result = await self.async_execute(ctx, endpoints=endpoints)
        return result.findings

    async def async_execute(
        self,
        ctx: ToolContext,
        endpoints: list[str] | None = None,
    ) -> UnifiedToolResult:
        """
        AsyncTool entry point.

        Creates a ``FindingBuilder`` from the context, maps ``ToolContext``
        settings, runs all API security checks (BOLA, mass assignment,
        auth bypass, rate limiting), and returns a ``UnifiedToolResult``
        with findings.

        Args:
            ctx: Tool execution context with target, engagement_id, etc.
            endpoints: Optional list of pre-discovered API endpoint paths.
                       When ``None`` (default), triggers automatic endpoint
                       discovery via ``discover_endpoints()``.
                       Provide explicit endpoints to avoid relying on discovery.

        Returns:
            ``UnifiedToolResult`` with findings from all API security checks.
        """
        builder = FindingBuilder(
            source_tool=self.tool_name,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding,
        )

        # Map ToolContext timeout
        if ctx.timeout:
            self.timeout = ctx.timeout

        base_url = ctx.target
        self._builder = builder

        slog = ScanLogger("api_security_scanner")

        if not is_enabled("API_SCANNER", default=False):
            slog.info("API security scanner disabled (ARGUS_FF_API_SCANNER not set)")
            result = UnifiedToolResult(tool_name=self.tool_name, target=base_url)
            result.status = ToolStatus.SUCCESS
            result.mark_finished()
            return result

        self._validate_external_url(base_url)

        # When endpoints are not provided, pass empty list to trigger discovery
        scan_endpoints = [] if endpoints is None else endpoints
        if not scan_endpoints:
            slog.info("No endpoints provided, running discovery...")
            scan_endpoints = await self.discover_endpoints(base_url)
            if not scan_endpoints:
                result = UnifiedToolResult(tool_name=self.tool_name, target=base_url)
                result.mark_finished()
                return result

        auth_headers: dict[str, str] = getattr(self, '_scan_auth_headers', {})

        slog.phase_header("API SECURITY SCAN", f"{len(scan_endpoints)} endpoints")

        slog.tool_start("bola", f"{len(scan_endpoints)} endpoints")
        await self._test_bola(base_url, scan_endpoints, auth_headers)
        slog.tool_complete("bola", findings=len(builder.findings))

        slog.tool_start("mass_assignment", f"{len(scan_endpoints)} endpoints")
        await self._test_mass_assignment(base_url, scan_endpoints, auth_headers)
        slog.tool_complete("mass_assignment")

        slog.tool_start("auth_bypass", f"{len(scan_endpoints)} endpoints")
        await self._test_auth_bypass(base_url, scan_endpoints)
        slog.tool_complete("auth_bypass")

        slog.tool_start("rate_limiting", f"{len(scan_endpoints)} endpoints")
        await self._test_api_rate_limiting(base_url, scan_endpoints, auth_headers)
        slog.tool_complete("rate_limiting")

        slog.tool_complete("api_security_scan", findings=len(builder.findings))

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=base_url,
        )
        result.findings = builder.findings
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    # ------------------------------------------------------------------
    # BOLA / IDOR
    # ------------------------------------------------------------------

    async def _test_bola(
        self,
        base_url: str,
        endpoints: list[str],
        auth_headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Detect BOLA by replacing ID-like path segments and comparing responses.

        Read-only approach: sends two requests (original ID and alt ID) and
        compares response sizes/content. A similar-sized response with the
        alt ID suggests the endpoint lacks proper authorization.

        Findings are also registered via ``self._builder`` for the
        ``async_execute()`` entry point.
        """
        findings: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for endpoint in endpoints:
                alt_url = self._try_replace_id(endpoint)
                if alt_url is None:
                    continue

                full_original = urljoin(base_url, endpoint)
                full_alt = urljoin(base_url, alt_url)

                try:
                    orig_resp = await client.get(
                        full_original, headers=auth_headers
                    )
                    alt_resp = await client.get(full_alt, headers=auth_headers)
                except httpx.RequestError:
                    continue

                if orig_resp.status_code in (401, 403) or alt_resp.status_code in (401, 403):
                    continue

                alt_resp_404 = alt_resp.status_code == 404

                if not alt_resp_404 and alt_resp.status_code == 200 and orig_resp.status_code == 200:
                    orig_body = orig_resp.text
                    alt_body = alt_resp.text
                    size_ratio = len(alt_body) / max(len(orig_body), 1)

                    if 0.8 <= size_ratio <= 1.2 and alt_body != orig_body:
                        evidence = {
                            "original_url": full_original,
                            "altered_url": full_alt,
                            "original_status": orig_resp.status_code,
                            "altered_status": alt_resp.status_code,
                            "original_size": len(orig_body),
                            "altered_size": len(alt_body),
                            "size_ratio": round(size_ratio, 3),
                            "detail": (
                                "Response to altered user ID is similar in size "
                                "to the original, suggesting BOLA/IDOR"
                            ),
                        }
                        findings.append(self._add_finding(
                            "API_BOLA", "HIGH", full_original,
                            evidence, confidence=0.7,
                        ))

                # Different status codes (not 401/403/404) → potential BOLA
                if not alt_resp_404 and orig_resp.status_code != alt_resp.status_code:
                    evidence = {
                        "original_url": full_original,
                        "altered_url": full_alt,
                        "original_status": orig_resp.status_code,
                        "altered_status": alt_resp.status_code,
                        "original_size": len(orig_resp.text),
                        "altered_size": len(alt_resp.text),
                        "detail": (
                            "Altered ID produced a different status code "
                            "but not a 404"
                        ),
                    }
                    findings.append(self._add_finding(
                        "API_BOLA", "MEDIUM", full_original,
                        evidence, confidence=0.5,
                    ))

        return findings

    @staticmethod
    def _try_replace_id(endpoint: str) -> str | None:
        """Replace the last path segment that looks like an ID with an alt ID.

        Returns the modified path or None if no ID-like segment was found.
        """
        parts = endpoint.strip("/").split("/")
        for i in range(len(parts) - 1, -1, -1):
            if re.match(r"^[0-9a-f]{8,}$", parts[i], re.IGNORECASE):
                parts[i] = "00000000-0000-0000-0000-000000000000"
                return "/" + "/".join(parts)
            if re.match(r"^\d+$", parts[i]):
                alt = "456" if parts[i] != "456" else "999"
                parts[i] = alt
                return "/" + "/".join(parts)
            if re.match(r"^[0-9a-f]{24}$", parts[i], re.IGNORECASE):
                parts[i] = "000000000000000000000000"
                return "/" + "/".join(parts)
        return None

    # ------------------------------------------------------------------
    # Mass Assignment
    # ------------------------------------------------------------------

    async def _test_mass_assignment(
        self,
        base_url: str,
        endpoints: list[str],
        auth_headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Send extra privilege-related fields in POST/PUT bodies.

        Checks if the server reflects the injected fields in its response,
        which indicates the extra fields were accepted.
        Findings are registered via ``self._builder`` and returned as a list.
        """

        findings: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for endpoint in endpoints:
                for payload in self.MASS_ASSIGNMENT_PAYLOADS:
                    for method in ("POST", "PUT", "PATCH"):
                        full_url = urljoin(base_url, endpoint)
                        try:
                            resp = await client.request(
                                method,
                                full_url,
                                headers=auth_headers,
                                json=payload,
                            )
                        except httpx.RequestError:
                            continue

                        if resp.status_code in (401, 403, 404, 405, 501) or resp.status_code >= 500:
                            continue

                        body = resp.text
                        for key, value in payload.items():
                            key_in_body = key.lower() in body.lower()
                            value_in_body = (
                                str(value).lower() in body.lower()
                            )
                            if key_in_body or value_in_body:
                                evidence = {
                                    "method": method,
                                    "payload": payload,
                                    "response_status": resp.status_code,
                                    "reflected_key": key,
                                    "reflected_key_found": key_in_body,
                                    "reflected_value_found": value_in_body,
                                    "detail": (
                                        f"Extra field '{key}' was reflected "
                                        f"in the response"
                                    ),
                                }
                                findings.append(self._add_finding(
                                    "API_MASS_ASSIGNMENT", "HIGH", full_url,
                                    evidence, confidence=0.6,
                                ))

        return findings

    # ------------------------------------------------------------------
    # Auth Bypass
    # ------------------------------------------------------------------

    async def _test_auth_bypass(
        self,
        base_url: str,
        endpoints: list[str],
    ) -> list[dict[str, Any]]:
        """Send requests with missing or malformed auth headers.

        Flags endpoints that return 200 without valid authentication.
        Findings are registered via ``self._builder`` and returned as a list.
        """

        findings: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for endpoint in endpoints:
                if any(endpoint.startswith(p) for p in self.PUBLIC_ENDPOINT_PATTERNS):
                    continue
                for headers in self.AUTH_HEADER_VARIANTS:
                    full_url = urljoin(base_url, endpoint)
                    # R-02: Test GET, POST, and PUT — different methods may
                    # have different auth enforcement on the same endpoint.
                    for method in ("GET", "POST", "PUT"):
                        try:
                            kwargs: dict[str, Any] = {"headers": headers or {}}
                            if method in ("POST", "PUT"):
                                kwargs["json"] = {}
                            resp = await client.request(method, full_url, **kwargs)
                        except httpx.RequestError:
                            continue

                        if resp.status_code == 200:
                            label = (
                                "no auth headers"
                                if headers is None
                                else f"auth variant: {headers}"
                            )
                            evidence = {
                                "auth_headers_used": headers,
                                "method": method,
                                "response_status": resp.status_code,
                                "response_size": len(resp.text),
                                "detail": (
                                    f"{method} returned 200 with {label}"
                                ),
                            }
                            findings.append(self._add_finding(
                                "API_AUTH_BYPASS", "CRITICAL", full_url,
                                evidence, confidence=0.5,
                            ))

        return findings

    # ------------------------------------------------------------------
    # Rate Limiting
    # ------------------------------------------------------------------

    async def _test_api_rate_limiting(
        self,
        base_url: str,
        endpoints: list[str],
        auth_headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Send a burst of rapid requests to auth-related endpoints.

        Checks for 429 Too Many Requests responses.
        Findings are registered via ``self._builder`` and returned as a list.
        """
        findings: list[dict[str, Any]] = []

        auth_endpoints = [
            ep for ep in endpoints
            if any(kw in ep.lower() for kw in ("login", "auth", "token", "signin", "signup", "register"))
        ]

        if not auth_endpoints:
            return findings

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for endpoint in auth_endpoints:
                full_url = urljoin(base_url, endpoint)
                rate_limited = False
                status_counts: dict[int, int] = {}
                chunks = [
                    list(range(self.RATE_LIMIT_REQUEST_COUNT))[i:i + self.RATE_LIMIT_CONCURRENCY]
                    for i in range(0, self.RATE_LIMIT_REQUEST_COUNT, self.RATE_LIMIT_CONCURRENCY)
                ]

                for chunk in chunks:
                    tasks = [
                        client.get(full_url, headers=auth_headers)
                        for _ in chunk
                    ]
                    try:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                    except Exception:
                        continue

                    for result in results:
                        if isinstance(result, Exception):
                            continue
                        status_counts[result.status_code] = (
                            status_counts.get(result.status_code, 0) + 1
                        )
                        if result.status_code == 429:
                            rate_limited = True

                if rate_limited:
                    evidence = {
                        "requests_sent": self.RATE_LIMIT_REQUEST_COUNT,
                        "status_distribution": status_counts,
                        "detail": "Server implements rate limiting (429 detected)",
                    }
                    findings.append(self._add_finding(
                        "API_RATE_LIMITED", "INFO", full_url,
                        evidence, confidence=0.9,
                    ))
                else:
                    if not status_counts:
                        evidence = {
                            "requests_sent": self.RATE_LIMIT_REQUEST_COUNT,
                            "status_distribution": {},
                            "detail": "All requests failed — rate limit test inconclusive",
                        }
                        findings.append(self._add_finding(
                            "API_RATE_LIMIT_INCONCLUSIVE", "INFO", full_url,
                            evidence, confidence=0.3,
                        ))
                        continue
                    non_error_codes = [c for c in status_counts if c < 500]
                    total_ok = sum(status_counts.get(c, 0) for c in non_error_codes)
                    if total_ok >= self.RATE_LIMIT_REQUEST_COUNT * 0.8:
                        evidence = {
                            "requests_sent": self.RATE_LIMIT_REQUEST_COUNT,
                            "status_distribution": status_counts,
                            "detail": (
                                "Server accepted most requests without "
                                "rate limiting"
                            ),
                        }
                        findings.append(self._add_finding(
                            "API_NO_RATE_LIMIT", "MEDIUM", full_url,
                            evidence, confidence=0.6,
                        ))

        return findings

    # ------------------------------------------------------------------
    # Endpoint Discovery
    # ------------------------------------------------------------------

    @staticmethod
    async def discover_endpoints(base_url: str) -> list[str]:
        """Discover API endpoints from JS sources, known patterns, and OpenAPI docs.

        Args:
            base_url: Base URL of the target application.

        Returns:
            Deduplicated list of discovered endpoint paths.
        """
        discovered: set[str] = set()

        APISecurityScanner._validate_external_url(base_url)

        # 1. Try common OpenAPI / API doc paths
        doc_paths = [
            "/api-docs", "/swagger.json", "/openapi.json",
            "/api/swagger.json", "/api/openapi.json",
            "/v1/api-docs", "/v2/api-docs",
            "/.well-known/openid-configuration",
        ]
        for doc_path in doc_paths:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(urljoin(base_url, doc_path))
                    if resp.status_code == 200:
                        paths = APISecurityScanner._extract_openapi_paths(
                            resp.text, resp.headers.get("content-type", "")
                        )
                        discovered.update(paths)
                        if paths:
                            break
            except (httpx.RequestError, Exception):
                continue

        # 2. Scan known API path patterns
        for api_path in APISecurityScanner.KNOWN_API_PATHS:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(urljoin(base_url, api_path))
                    if resp.status_code != 404:
                        discovered.add(api_path)
            except httpx.RequestError:
                continue

        # 3. Try to fetch main page and scan JS for API calls
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(base_url)
                if resp.status_code == 200:
                    js_api = APISecurityScanner._extract_api_from_html(
                        resp.text, base_url
                    )
                    discovered.update(js_api)
        except httpx.RequestError:
            pass

        return sorted(discovered)

    @staticmethod
    def _extract_openapi_paths(
        body: str, content_type: str
    ) -> list[str]:
        """Parse OpenAPI spec JSON (only) for endpoint paths. YAML is not supported."""
        paths: list[str] = []
        if "json" in content_type or body.strip().startswith("{"):
            try:
                import json
                spec = json.loads(body)
                if "paths" in spec:
                    for path in spec["paths"]:
                        paths.append(path)
            except json.JSONDecodeError:
                logger.warning("Failed to parse OpenAPI JSON body — YAML not supported")
            except Exception:
                logger.debug("Failed to parse OpenAPI spec (non-json body)", exc_info=True)
        return paths

    @staticmethod
    def _extract_api_from_html(html: str, base_url: str) -> list[str]:
        """Extract API endpoint URLs from HTML and inline JS."""
        urls: set[str] = set()
        base_domain = urlparse(base_url).netloc

        # fetch/XHR calls in JS
        patterns = [
            r"""fetch\s*\(\s*['"]([^'"]+)['"]""",
            r"""\baxios\b[^;]*['"]([^'"]+)['"]""",
            r"""\bajax\s*\([^)]*['"]([^'"]+)['"]""",
            r"""XMLHttpRequest[^;]*['"]([^'"]+)['"]""",
            r"""\$\.(?:get|post|put|delete|ajax)\s*\(\s*['"]([^'"]+)['"]""",
            r"""\bapi\.(?:get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""",
        ]

        for pattern in patterns:
            for match in re.findall(pattern, html, re.IGNORECASE):
                path = match.strip()
                if path.startswith("/"):
                    urls.add(path)
                elif path.startswith("http"):
                    parsed = urlparse(path)
                    if parsed.netloc == base_domain:
                        urls.add(parsed.path)
                elif not path.startswith(("data:", "blob:", "javascript:")):
                    urls.add("/" + path.lstrip("/"))

        return list(urls)
