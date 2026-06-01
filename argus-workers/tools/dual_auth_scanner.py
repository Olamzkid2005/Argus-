"""
DualAuthScanner — Cross-account BOLA/BOPLA testing with two authenticated sessions.

Requires auth_config for User A and auth_config for User B.
User A creates/discoveres resources → User B attempts to access them.
A 200 response where User B retrieves User A's data = confirmed BOLA.
"""

import json
import logging
import re
import threading
import time
from typing import Callable
from urllib.parse import urljoin

import requests
import urllib3
from requests.exceptions import ConnectionError, RequestException, Timeout

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class DualAuthScanner(AbstractTool):
    """Scanner for cross-account access control testing (BOLA/BOPLA/IDOR)."""

    # Resource patterns to discover in API responses
    RESOURCE_PATTERNS = {
        "accounts": r'/(?:api/)?accounts?/(\d+)',
        "users": r'/(?:api/)?users?/(\d+)',
        "cards": r'/(?:api/)?cards?/(\d+)',
        "payments": r'/(?:api/)?payments?/(\d+)',
        "transactions": r'/(?:api/)?transactions?/(\d+)',
        "orders": r'/(?:api/)?orders?/(\d+)',
        "profiles": r'/(?:api/)?profiles?/(\d+)',
        "documents": r'/(?:api/)?documents?/(\d+)',
        "invoices": r'/(?:api/)?invoices?/(\d+)',
    }

    # HTTP methods to test for each discovered resource.
    # DELETE is excluded (L-08): sending DELETE against User A's resources
    # from User B's session actually destroys data if BOLA is present.
    # Cross-account DELETE testing requires explicit opt-in and a
    # non-production environment.
    TEST_METHODS = ["GET", "PUT"]

    # Sensitive fields blocklist (BOPLA) — shared with WebScanner via import
    # See: tools.web_scanner.WebScanner.SENSITIVE_RESPONSE_FIELDS

    # Known "access denied" indicators
    ACCESS_DENIED_INDICATORS = [
        "access denied", "forbidden", "unauthorized", "not authorized",
        "permission denied", "insufficient privilege", "not found",
        "does not exist", "cannot access",
    ]

    def __init__(
        self,
        auth_config_a: dict | None = None,
        auth_config_b: dict | None = None,
        timeout: int = 60,
        rate_limit: float = 0.3,
        verify: bool = True,
        engagement_id: str = "",
        emit_finding_callback=None,
    ):
        """
        Args:
            auth_config_a: AuthConfig for User A (resource owner).
            auth_config_b: AuthConfig for User B (attacker trying cross-account access).
            timeout: HTTP request timeout in seconds.
            rate_limit: Seconds between requests.
            verify: SSL certificate verification.
            engagement_id: Engagement ID for log/trace correlation.
            emit_finding_callback: Optional callable(engagement_id, finding_dict, tool_name)
                                   called inline per finding for real-time streaming.
        """
        from tools.auth_manager import AuthConfig, AuthManager

        self.auth_config_a = None
        self.auth_config_b = None
        self.auth_manager_a = None
        self.auth_manager_b = None
        if auth_config_a:
            self.auth_config_a = AuthConfig(**auth_config_a) if isinstance(auth_config_a, dict) else auth_config_a
            self.auth_manager_a = AuthManager(self.auth_config_a)
        if auth_config_b:
            self.auth_config_b = AuthConfig(**auth_config_b) if isinstance(auth_config_b, dict) else auth_config_b
            self.auth_manager_b = AuthManager(self.auth_config_b)
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.verify = verify
        self.engagement_id = engagement_id
        self.emit_finding_callback = emit_finding_callback
        self.findings: list[dict] = []
        self._builder: FindingBuilder | None = None
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()

    @classmethod
    def for_phase_execution(
        cls,
        *,
        target: str,
        engagement_id: str,
        emit_finding: Callable | None,
        source_tool: str,
        timeout: int = 60,
        rate_limit: float = 0.3,
        verify: bool = True,
    ) -> "DualAuthScanner":
        """Construct a DualAuthScanner instance for use as a step helper.

        Bypasses __init__ to avoid the heavy auth_manager_a/b setup that the workflow
        doesn't need (workflow has its own auth via AuthManager). Only the fields
        required by the private methods (_discover_owned_resources,
        _test_cross_account_access, _check_bopla, _safe_request) are set.

        The resulting instance has:
          - _builder = FindingBuilder(...) so all findings go through validation,
            evidence sanitization, and SSE streaming via emit_finding callback
          - _last_response_received = False; flipped to True by the wrapped
            _safe_request when any request returns a non-None response (ANY HTTP
            response, including 4xx/5xx — because a TCP-level response means the
            target IS reachable). Steps check this flag to decide whether to emit
            a target_unreachable obstacle (all requests failed at the transport
            level, not just returned errors).

        IMPORTANT: Any new attribute added to __init__ that is read by the private
        methods MUST also be added here. Enforced by tests that introspect both
        __init__ and for_phase_execution for matching attributes.
        """
        instance = cls.__new__(cls)
        instance.auth_config_a = None
        instance.auth_config_b = None
        instance.auth_manager_a = None
        instance.auth_manager_b = None
        instance.timeout = timeout
        instance.rate_limit = rate_limit
        instance.verify = verify
        instance.engagement_id = engagement_id
        instance.emit_finding_callback = emit_finding
        instance.findings = []
        instance._last_request_time = 0.0
        instance._rate_lock = threading.Lock()
        instance._last_response_received = False
        instance.target_url = target.rstrip("/")

        # CRITICAL: set _builder so _emit_finding routes through FindingBuilder.
        # Without this, findings skip severity validation + evidence sanitization.
        instance._builder = FindingBuilder(
            source_tool=source_tool,
            engagement_id=engagement_id,
            emit_finding=emit_finding,
        )

        # Wrap _safe_request to track _last_response_received.
        # ANY non-None response (including 4xx/5xx) means the target is reachable.
        original_safe_request = cls._safe_request

        def wrapped_safe_request(
            self_: "DualAuthScanner", method: str, url: str, session: requests.Session, **kwargs: object
        ) -> requests.Response | None:
            result = original_safe_request(self_, method, url, session, **kwargs)
            if result is not None:
                self_._last_response_received = True
            return result

        instance._safe_request = wrapped_safe_request.__get__(instance, cls)  # type: ignore[method-assign]
        return instance

    def _emit_finding(self, finding: dict) -> None:
        """Emit a finding in real-time if callback is configured.

        When ``self._builder`` is available (called via ``execute()``), the
        finding is registered through ``FindingBuilder.add()`` for standardized
        creation, evidence sanitization, and severity validation.  When called
        directly (backward compat), the raw dict is appended to
        ``self.findings`` as before.
        """
        if self._builder:
            finding = self._builder.add(
                finding.get("type", "UNKNOWN"),
                finding.get("severity", "INFO"),
                finding.get("endpoint", ""),
                finding.get("evidence", {}),
                confidence=finding.get("confidence", 0.8),
            )
        self.findings.append(finding)
        if self.emit_finding_callback and self.engagement_id:
            try:
                self.emit_finding_callback(self.engagement_id, finding, "dual_auth_scanner")
            except Exception:
                logger.debug("Inline finding emission failed (non-fatal)", exc_info=True)

    tool_name = "dual_auth_scanner"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        AbstractTool entry point.

        Creates a ``FindingBuilder`` from the context, maps ``ToolContext``
        settings, runs all checks (auth phases, resource discovery,
        cross-account access, BOPLA), and returns a ``UnifiedToolResult``
        with findings.

        Auth configs are read from ``ctx.dual_auth`` when available (the
        canonical path via ``execute()``).  Falls back to constructor-set
        ``self.auth_manager_*`` for backward compatibility with callers
        that instantiate the scanner with constructor params and call
        ``scan()`` (which creates a bare ``ToolContext`` with no dual_auth).
        """
        self._builder = FindingBuilder(
            source_tool=self.tool_name,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding,
        )

        # Map ToolContext settings
        if ctx.timeout:
            self.timeout = ctx.timeout
        if ctx.rate_limit:
            self.rate_limit = ctx.rate_limit
        if ctx.engagement_id:
            self.engagement_id = ctx.engagement_id

        # Read auth configs from ToolContext (canonical path)
        if ctx.dual_auth:
            from tools.auth_manager import AuthConfig as _AuthCfg, AuthManager as _AuthMgr
            self.auth_config_a = _AuthCfg(**ctx.dual_auth.auth_a)
            self.auth_config_b = _AuthCfg(**ctx.dual_auth.auth_b)
            self.auth_manager_a = _AuthMgr(self.auth_config_a)
            self.auth_manager_b = _AuthMgr(self.auth_config_b)

        target_url = ctx.target
        slog = ScanLogger("dual_auth_scanner", engagement_id=self.engagement_id)
        self.target_url = target_url.rstrip("/")
        self.findings: list[dict] = []

        slog.phase_header("Dual-Auth Scan", target=self.target_url)
        logger.info(f"Starting dual-auth scan: {self.target_url}")

        # Phase 1: Authenticate as User A and discover owned resources
        slog.info("Phase 1: Authenticating as User A")
        session_a = None
        session_b = None
        try:
            session_a = self.auth_manager_a.authenticate(self.target_url)
            slog.info("User A authenticated")
            logger.info("User A authenticated successfully")
        except Exception as e:
            slog.warn(f"User A authentication failed: {e}")
            logger.warning(f"User A authentication failed: {e}")

        if session_a:
            slog.tool_start("resource_discovery")
            owned_resources = self._discover_owned_resources(session_a)
            resource_count = sum(len(v) for v in owned_resources.values())
            slog.tool_complete("resource_discovery", findings=resource_count)
            logger.info(f"Discovered {resource_count} resources as User A")

            if not owned_resources:
                slog.info("No owned resources — skipping cross-account tests")
                # Still run BOPLA check on User A session
                for bopla in self._check_bopla(session_a, "user_a"):
                    self._emit_finding(bopla)
            else:
                # Phase 2: Authenticate as User B and test cross-account access
                slog.info("Phase 2: Authenticating as User B")
                try:
                    session_b = self.auth_manager_b.authenticate(self.target_url)
                    slog.info("User B authenticated")
                    logger.info("User B authenticated successfully")
                except Exception as e:
                    slog.warn(f"User B authentication failed: {e}")
                    logger.warning(f"User B authentication failed: {e}")

                if session_b:
                    slog.tool_start("cross_account_access")
                    bola_findings = self._test_cross_account_access(session_b, owned_resources)
                    for bf in bola_findings:
                        self._emit_finding(bf)
                    slog.tool_complete("cross_account_access", findings=len(bola_findings))

                    # Phase 3: BOPLA check on both sessions
                    slog.info("Phase 3: Checking BOPLA on both sessions")
                    for bopla in self._check_bopla(session_a, "user_a"):
                        self._emit_finding(bopla)
                    for bopla in self._check_bopla(session_b, "user_b"):
                        self._emit_finding(bopla)
                else:
                    # No User B — still run BOPLA on User A
                    for bopla in self._check_bopla(session_a, "user_a"):
                        self._emit_finding(bopla)

        slog.tool_complete("dual_auth_scan", findings=len(self.findings))
        logger.info(f"Dual-auth scan complete: {len(self.findings)} findings")

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
        )
        result.findings = self._builder.findings
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def scan(self, target_url: str) -> list[dict]:
        """
        Run dual-auth scan against target.

        Backward-compatible shim that delegates to ``execute()``. Existing
        callers that call ``scan()`` directly still work unchanged.

        1. Authenticate as User A, discover owned resources.
        2. Authenticate as User B, attempt cross-account access.
        3. Check BOPLA on both sessions.

        Returns:
            List of vulnerability finding dicts.
        """
        ctx = ToolContext(target=target_url)
        result = self.execute(ctx)
        return result.findings

    # --- Private helpers ---

    def _safe_request(
        self,
        method: str,
        url: str,
        session: requests.Session,
        **kwargs,
    ) -> requests.Response | None:
        """Make HTTP request with rate limiting and error handling."""
        try:
            kwargs.setdefault("timeout", self.timeout)
            kwargs.setdefault("allow_redirects", True)
            kwargs.setdefault("verify", self.verify)

            with self._rate_lock:
                now = time.time()
                wait_time = self._last_request_time + self.rate_limit - now
                if wait_time > 0:
                    time.sleep(wait_time)
                self._last_request_time = time.time()

            resp = session.request(method, url, **kwargs)
            return resp
        except (TimeoutError, RequestException, Timeout, ConnectionError, urllib3.exceptions.SSLError) as e:
            logger.debug(f"DualAuth request failed: {e}")
            return None

    def _discover_owned_resources(self, session: requests.Session) -> dict[str, list[str]]:
        """Crawl target as User A and discover resource IDs owned by this user."""
        discovered: dict[str, list[str]] = {}

        # Phase A: Fetch the target root and common API entrypoints
        endpoints_to_probe = [self.target_url]
        api_paths = [
            "/api/v1/accounts", "/api/accounts", "/api/v1/users", "/api/users",
            "/api/v1/cards", "/api/cards", "/api/v1/payments", "/api/payments",
            "/api/v1/transactions", "/api/transactions", "/api/v1/orders", "/api/orders",
            "/api/v1/profile", "/api/profile", "/api/v1/me", "/api/me",
        ]
        for api_path in api_paths:
            endpoints_to_probe.append(urljoin(self.target_url, api_path))

        seen_urls = set()
        for url in endpoints_to_probe[:5]:  # Limit to 5 probes
            if url in seen_urls:
                continue
            seen_urls.add(url)

            resp = self._safe_request("GET", url, session=session)
            if not resp or resp.status_code != 200:
                continue

            text = resp.text

            # Phase B: Extract IDs from response using resource patterns
            for resource_type, pattern in self.RESOURCE_PATTERNS.items():
                matches = re.findall(pattern, text)
                if matches:
                    if resource_type not in discovered:
                        discovered[resource_type] = []
                    discovered[resource_type].extend(matches)

            # Phase C: Also try parsing JSON responses for ID fields
            try:
                data = resp.json()
                self._extract_ids_from_json(data, discovered, _resource_type_hint=None)
            except (json.JSONDecodeError, ValueError):
                pass

            # Phase D: Discover more endpoint paths from the response
            link_pattern = r'href=["\']([^"\']*(?:/api/[^"\']*/\d+)[^"\']*)["\']'
            links = re.findall(link_pattern, text)
            for link in links[:5]:
                absolute = urljoin(self.target_url, link)
                if absolute.startswith(self.target_url) and absolute not in seen_urls:
                    seen_urls.add(absolute)
                    r = self._safe_request("GET", absolute, session=session)
                    if r and r.status_code == 200:
                        for resource_type, pattern in self.RESOURCE_PATTERNS.items():
                            matches = re.findall(pattern, r.text)
                            if matches:
                                if resource_type not in discovered:
                                    discovered[resource_type] = []
                                discovered[resource_type].extend(matches)

        # Deduplicate IDs per resource type
        for resource_type in discovered:
            discovered[resource_type] = list(set(discovered[resource_type]))

        return discovered

    def _extract_ids_from_json(
        self,
        data,
        discovered: dict,
        _resource_type_hint: str | None = None,
    ) -> None:
        """Recursively extract ID values from JSON structures."""
        if isinstance(data, dict):
            for key, value in data.items():
                # If key looks like an ID field and value is a number
                if key in ("id", "user_id", "account_id", "card_id", "payment_id",
                            "transaction_id", "order_id") and isinstance(value, (int, str)):
                    resource_type = key.replace("_id", "").replace("id", "generic") if key != "id" else "generic"
                    if resource_type not in discovered:
                        discovered[resource_type] = []
                    discovered[resource_type].append(str(value))
                self._extract_ids_from_json(value, discovered)
        elif isinstance(data, list):
            for item in data[:10]:
                self._extract_ids_from_json(item, discovered)

    def _test_cross_account_access(
        self,
        session_b: requests.Session,
        owned_resources: dict[str, list[str]],
    ) -> list[dict]:
        """Test whether User B can access resources owned by User A."""
        findings = []

        # Build a map of resource type → URL template
        resource_urls = {
            "accounts": "/api/accounts/{}",
            "users": "/api/users/{}",
            "cards": "/api/cards/{}",
            "payments": "/api/payments/{}",
            "transactions": "/api/transactions/{}",
            "orders": "/api/orders/{}",
            "profiles": "/api/profiles/{}",
            "documents": "/api/documents/{}",
            "invoices": "/api/invoices/{}",
        }

        tested = 0
        for resource_type, ids in owned_resources.items():
            template = resource_urls.get(resource_type)
            if not template:
                continue

            for resource_id in ids[:3]:  # Limit to 3 IDs per type
                for method in self.TEST_METHODS:
                    url = urljoin(self.target_url, template.format(resource_id))
                    tested += 1
                    if tested > 30:  # Safety cap
                        return findings

                    kwargs = {}
                    if method in ("PUT",):
                        kwargs["json"] = {"test": "bola_check"}
                        kwargs["headers"] = {"Content-Type": "application/json"}

                    resp = self._safe_request(method, url, session=session_b, **kwargs)
                    if not resp:
                        continue

                    # Check if User B successfully accessed User A's resource
                    if resp.status_code in (200, 201):
                        response_text = resp.text.lower()
                        is_access_denied = any(
                            indicator in response_text
                            for indicator in self.ACCESS_DENIED_INDICATORS
                        )

                        if not is_access_denied and len(resp.text) > 50:
                            # Confirmed BOLA — User B can see/use User A's resource
                            findings.append({
                                "type": "CONFIRMED_BOLA",
                                "severity": "CRITICAL",
                                "endpoint": url,
                                "evidence": {
                                    "resource_type": resource_type,
                                    "resource_id": resource_id,
                                    "method": method,
                                    "response_status": resp.status_code,
                                    "response_preview": resp.text[:200],
                                    "message": f"User B successfully accessed User A's {resource_type} resource via {method}",
                                },
                                "confidence": 0.9,
                            })
                            break  # One confirmed BOLA per resource is enough
                        elif resp.status_code == 200:
                            # Potential BOLA — response exists but unclear if access was granted
                            findings.append({
                                "type": "POTENTIAL_BOLA",
                                "severity": "MEDIUM",
                                "endpoint": url,
                                "evidence": {
                                    "resource_type": resource_type,
                                    "resource_id": resource_id,
                                    "method": method,
                                    "response_status": resp.status_code,
                                    "response_size": len(resp.text),
                                    "message": f"User B received 200 for User A's {resource_type} — response ambiguous",
                                },
                                "confidence": 0.5,
                            })

        return findings

    def _check_bopla(self, session: requests.Session, role_label: str) -> list[dict]:
        """Check API responses for sensitive fields that shouldn't be exposed."""
        findings = []

        api_endpoints = [
            "/api/v1/users", "/api/users", "/api/v1/accounts", "/api/accounts",
            "/api/v1/me", "/api/me", "/api/profile",
        ]

        for path in api_endpoints:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url, session=session,
                                       headers={"Content-Type": "application/json"})
            if not resp or resp.status_code != 200:
                continue

            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError):
                continue

            data_str = json.dumps(data).lower()
            exposed_fields = []
            # Shared source of truth with WebScanner.SENSITIVE_RESPONSE_FIELDS
            from tools.web_scanner import WebScanner
            sensitive_fields = WebScanner.SENSITIVE_RESPONSE_FIELDS
            for field in sensitive_fields:
                if f'"{field}"' in data_str:
                    exposed_fields.append(field)

            if exposed_fields:
                findings.append({
                    "type": "BOPLA_SENSITIVE_FIELDS",
                    "severity": "HIGH",
                    "endpoint": url,
                    "evidence": {
                        "role": role_label,
                        "exposed_fields": exposed_fields,
                        "response_keys": list(data.keys()) if isinstance(data, dict) else ["array"],
                        "message": f"API response for {role_label} exposes {len(exposed_fields)} sensitive fields",
                    },
                    "confidence": 0.85,
                })

        return findings
