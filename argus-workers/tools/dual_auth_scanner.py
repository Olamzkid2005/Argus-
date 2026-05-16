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
from urllib.parse import urljoin

import requests
import urllib3
from requests.exceptions import ConnectionError, RequestException, Timeout

from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class DualAuthScanner:
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

    # HTTP methods to test for each discovered resource
    TEST_METHODS = ["GET", "PUT", "DELETE"]

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
        auth_config_a: dict,
        auth_config_b: dict,
        timeout: int = 60,
        rate_limit: float = 0.3,
        verify: bool = True,
        engagement_id: str = "",
    ):
        """
        Args:
            auth_config_a: AuthConfig for User A (resource owner).
            auth_config_b: AuthConfig for User B (attacker trying cross-account access).
            timeout: HTTP request timeout in seconds.
            rate_limit: Seconds between requests.
            verify: SSL certificate verification.
            engagement_id: Engagement ID for log/trace correlation.
        """
        from tools.auth_manager import AuthConfig, AuthManager

        self.auth_config_a = AuthConfig(**auth_config_a) if isinstance(auth_config_a, dict) else auth_config_a
        self.auth_config_b = AuthConfig(**auth_config_b) if isinstance(auth_config_b, dict) else auth_config_b
        self.auth_manager_a = AuthManager(self.auth_config_a)
        self.auth_manager_b = AuthManager(self.auth_config_b)
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.verify = verify
        self.engagement_id = engagement_id
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()

    def scan(self, target_url: str) -> list[dict]:
        """
        Run dual-auth scan against target.

        1. Authenticate as User A, discover owned resources.
        2. Authenticate as User B, attempt cross-account access.
        3. Check BOPLA on both sessions.

        Returns:
            List of vulnerability finding dicts.
        """
        slog = ScanLogger("dual_auth_scanner", engagement_id=self.engagement_id)
        self.target_url = target_url.rstrip("/")
        findings = []

        slog.phase_header("Dual-Auth Scan", target=self.target_url)
        logger.info(f"Starting dual-auth scan: {self.target_url}")

        # Phase 1: Authenticate as User A and discover owned resources
        slog.info("Phase 1: Authenticating as User A")
        try:
            session_a = self.auth_manager_a.authenticate(self.target_url)
            slog.info("User A authenticated")
            logger.info("User A authenticated successfully")
        except Exception as e:
            slog.warn(f"User A authentication failed: {e}")
            logger.warning(f"User A authentication failed: {e}")
            return findings

        slog.tool_start("resource_discovery")
        owned_resources = self._discover_owned_resources(session_a)
        resource_count = sum(len(v) for v in owned_resources.values())
        slog.tool_complete("resource_discovery", findings=resource_count)
        logger.info(f"Discovered {resource_count} resources as User A")

        if not owned_resources:
            slog.info("No owned resources — skipping cross-account tests")
            # Still run BOPLA check on User A session
            findings.extend(self._check_bopla(session_a, "user_a"))
            slog.tool_complete("dual_auth_scan", findings=len(findings))
            return findings

        # Phase 2: Authenticate as User B and test cross-account access
        slog.info("Phase 2: Authenticating as User B")
        try:
            session_b = self.auth_manager_b.authenticate(self.target_url)
            slog.info("User B authenticated")
            logger.info("User B authenticated successfully")
        except Exception as e:
            slog.warn(f"User B authentication failed: {e}")
            logger.warning(f"User B authentication failed: {e}")
            # Still run BOPLA on User A session
            findings.extend(self._check_bopla(session_a, "user_a"))
            slog.tool_complete("dual_auth_scan", findings=len(findings))
            return findings

        slog.tool_start("cross_account_access")
        bola_findings = self._test_cross_account_access(session_b, owned_resources)
        findings.extend(bola_findings)
        slog.tool_complete("cross_account_access", findings=len(bola_findings))

        # Phase 3: BOPLA check on both sessions
        slog.info("Phase 3: Checking BOPLA on both sessions")
        findings.extend(self._check_bopla(session_a, "user_a"))
        findings.extend(self._check_bopla(session_b, "user_b"))

        slog.tool_complete("dual_auth_scan", findings=len(findings))
        logger.info(f"Dual-auth scan complete: {len(findings)} findings")
        return findings

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
                    if resp.status_code in (200, 201, 204):
                        response_text = resp.text.lower()
                        # 204 on DELETE = successfully deleted — confirmed BOLA
                        is_delete_success = resp.status_code == 204 and method == "DELETE"
                        is_access_denied = any(
                            indicator in response_text
                            for indicator in self.ACCESS_DENIED_INDICATORS
                        )

                        if is_delete_success:
                            findings.append({
                                "type": "CONFIRMED_BOLA",
                                "severity": "CRITICAL",
                                "endpoint": url,
                                "evidence": {
                                    "resource_type": resource_type,
                                    "resource_id": resource_id,
                                    "method": method,
                                    "response_status": resp.status_code,
                                    "message": f"User B successfully DELETED User A's {resource_type} resource (204 No Content)",
                                },
                                "confidence": 0.95,
                            })
                            break
                        elif not is_access_denied and len(resp.text) > 50:
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
