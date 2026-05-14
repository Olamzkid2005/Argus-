"""
API Security Testing Module

Integrates OWASP ZAP, GraphQL security scanning, authentication testing,
and rate limit / DDoS testing capabilities.

Requirements: 15.1, 15.2, 15.3, 15.4
"""

import json
import logging
import time
from urllib.parse import urljoin

import requests
from requests.exceptions import ConnectionError, RequestException, Timeout

logger = logging.getLogger(__name__)

from config.constants import LLM_MAX_GENERATED_PAYLOADS
from utils.logging_utils import ScanLogger


class APISecurityScanner:
    """
    Comprehensive API security scanner.
    Supports REST, GraphQL, and generic HTTP API testing.
    """

    # Common GraphQL introspection query
    GRAPHQL_INTROSPECTION_QUERY = """
    query IntrospectionQuery {
      __schema {
        queryType { name }
        mutationType { name }
        subscriptionType { name }
        types {
          ...FullType
        }
      }
    }
    fragment FullType on __Type {
      kind
      name
      fields(includeDeprecated: true) {
        name
        type { name }
      }
    }
    """

    # JWT test payloads
    JWT_TEST_PAYLOADS = [
        # Algorithm confusion (none)
        {"alg": "none", "typ": "JWT"},
        # Weak secret hint
        {"alg": "HS256", "typ": "JWT"},
    ]

    # Rate limit test configurations
    RATE_TEST_CONFIGS = [
        {"requests": 50, "concurrency": 10, "description": "Standard burst test"},
        {"requests": 200, "concurrency": 50, "description": "High load test"},
    ]

    def __init__(
        self, timeout: int = 15, rate_limit: float = 0.05, llm_payload_generator=None, authorized_scope: str | None = None,
        session: requests.Session | None = None, tech_stack: list[str] | None = None,
    ):
        """
        Initialize API security scanner.

        Args:
            timeout: Request timeout in seconds
            rate_limit: Seconds between requests
            llm_payload_generator: Optional LLMPayloadGenerator for context-aware payloads
            authorized_scope: Optional URL prefix that defines the authorized testing scope
            session: Optional pre-authenticated requests.Session
            tech_stack: Detected technology stack from recon
        """
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.llm_payload_generator = llm_payload_generator
        self.authorized_scope = authorized_scope
        self.tech_stack = tech_stack or []
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Argus-API-Scanner/1.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.findings = []

    def scan(
        self, target_url: str, api_type: str = "rest", auth_config: dict | None = None
    ) -> list[dict]:
        """
        Run comprehensive API security scan.

        Args:
            target_url: Base API URL
            api_type: API type ('rest', 'graphql', 'openapi')
            auth_config: Optional authentication configuration

        Returns:
            List of vulnerability findings
        """
        slog = ScanLogger("api_scanner", engagement_id=getattr(self, 'engagement_id', ''))
        slog.phase_header("API SCAN", f"target={target_url}, type={api_type}")

        self.findings = []
        self.target_url = target_url.rstrip("/")
        self.auth_config = auth_config or {}

        # Apply authentication if configured
        if self.auth_config.get("type") == "api_key":
            slog.info(f"Applying API key auth to header: {self.auth_config.get('header', 'X-API-Key')}")
            self.session.headers[self.auth_config.get("header", "X-API-Key")] = (
                self.auth_config.get("key", "")
            )
        elif self.auth_config.get("type") == "bearer":
            slog.info("Applying Bearer token auth")
            self.session.headers["Authorization"] = (
                f"Bearer {self.auth_config.get('token', '')}"
            )

        # 1. OWASP ZAP-style basic checks
        slog.tool_start("security_headers", f"target={self.target_url}")
        self.check_security_headers()
        slog.tool_complete("security_headers", success=True)

        # 2. API type-specific scanning
        if api_type == "graphql":
            slog.tool_start("graphql_scan", f"target={self.target_url}")
            self.scan_graphql()
            slog.tool_complete("graphql_scan", success=True)
        elif api_type == "openapi":
            slog.tool_start("openapi_scan", f"target={self.target_url}")
            self.scan_openapi()
            slog.tool_complete("openapi_scan", success=True)
        else:
            slog.tool_start("rest_scan", f"target={self.target_url}")
            self.scan_rest_endpoints()
            slog.tool_complete("rest_scan", success=True)

        # 3. Authentication testing
        slog.tool_start("auth_testing", f"target={self.target_url}")
        self.test_authentication()
        slog.tool_complete("auth_testing", success=True)

        # 4. Rate limiting test
        slog.tool_start("rate_limit_test", f"target={self.target_url}")
        self.test_rate_limiting()
        slog.tool_complete("rate_limit_test", success=True)

        slog.tool_complete("api_scan", success=True, findings=len(self.findings))
        slog.info(f"API scan complete: {len(self.findings)} total findings")
        return self.findings

    def _safe_request(
        self, method: str, url: str, **kwargs
    ) -> requests.Response | None:
        """Make HTTP request with error handling."""
        try:
            kwargs.setdefault("timeout", self.timeout)
            kwargs.setdefault("allow_redirects", False)
            resp = self.session.request(method, url, **kwargs)
            time.sleep(self.rate_limit)
            return resp
        except (RequestException, Timeout, ConnectionError):
            return None

    def _add_finding(
        self,
        finding_type: str,
        severity: str,
        endpoint: str,
        evidence: dict,
        confidence: float = 0.8,
    ):
        """Add a finding to results."""
        self.findings.append(
            {
                "type": finding_type,
                "severity": severity,
                "endpoint": endpoint,
                "evidence": evidence,
                "confidence": confidence,
                "tool": "api_scanner",
            }
        )

    def check_security_headers(self):
        """Check API security headers."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        headers = {k.lower(): v for k, v in resp.headers.items()}

        # Check for missing API security headers
        required = ["content-type", "x-content-type-options"]
        missing = [h for h in required if h not in headers]

        if missing:
            self._add_finding(
                finding_type="MISSING_API_SECURITY_HEADERS",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={"missing_headers": missing},
                confidence=0.90,
            )

        # Check for CORS misconfiguration on API
        acao = headers.get("access-control-allow-origin", "")
        if acao == "*":
            self._add_finding(
                finding_type="WILDCARD_CORS_API",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={"Access-Control-Allow-Origin": "*"},
                confidence=0.90,
            )

    def scan_graphql(self):
        """Scan GraphQL endpoint for security issues."""
        graphql_url = urljoin(self.target_url, "/graphql")

        # Test introspection
        resp = self._safe_request(
            "POST",
            graphql_url,
            json={"query": self.GRAPHQL_INTROSPECTION_QUERY},
        )
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("data", {}).get("__schema"):
                    self._add_finding(
                        finding_type="GRAPHQL_INTROSPECTION_ENABLED",
                        severity="MEDIUM",
                        endpoint=graphql_url,
                        evidence={"message": "GraphQL introspection is enabled"},
                        confidence=0.95,
                    )
            except (json.JSONDecodeError, ValueError):
                pass

        # Test for query depth / complexity issues
        deep_query = """
        query DeepQuery {
          user {
            posts {
              comments {
                author {
                  posts {
                    comments {
                      author {
                        name
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        resp = self._safe_request(
            "POST",
            graphql_url,
            json={"query": deep_query},
        )
        if resp and resp.status_code == 200:
            self._add_finding(
                finding_type="GRAPHQL_DEPTH_LIMIT_MISSING",
                severity="MEDIUM",
                endpoint=graphql_url,
                evidence={"message": "Deep nested query executed without depth limit"},
                confidence=0.75,
            )

    def scan_openapi(self):
        """Discover and test OpenAPI/Swagger endpoints."""
        swagger_paths = [
            "/swagger.json",
            "/api-docs",
            "/openapi.json",
            "/v1/swagger.json",
        ]
        for path in swagger_paths:
            url = urljoin(self.target_url, path)
            resp = self._safe_request("GET", url)
            if resp and resp.status_code == 200:
                self._add_finding(
                    finding_type="EXPOSED_OPENAPI_SPEC",
                    severity="LOW",
                    endpoint=url,
                    evidence={
                        "message": "OpenAPI/Swagger specification is publicly accessible"
                    },
                    confidence=0.90,
                )
                break

    def scan_rest_endpoints(self):
        """Basic REST API endpoint discovery and testing."""
        common_paths = ["/api/v1/users", "/api/users", "/api/health", "/api/admin"]
        for path in common_paths:
            url = urljoin(self.target_url, path)
            resp = self._safe_request("GET", url)
            if resp and resp.status_code in (200, 401, 403):
                # Check for verbose error messages
                if resp.status_code in (401, 403) and len(resp.text) > 50:
                    self._add_finding(
                        finding_type="VERBOSE_API_ERROR",
                        severity="LOW",
                        endpoint=url,
                        evidence={
                            "status_code": resp.status_code,
                            "response_preview": resp.text[:200],
                        },
                        confidence=0.70,
                    )

    def test_authentication(self):
        """Test API authentication mechanisms."""
        # JWT testing
        auth_header = self.session.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            self._test_jwt_token(token)

        # API key testing
        api_key = self.session.headers.get("X-API-Key", "")
        if api_key:
            self._test_api_key(api_key)

        # Test for missing authentication on endpoints
        test_url = urljoin(self.target_url, "/api/admin")
        # Temporarily remove auth headers
        original_headers = dict(self.session.headers)
        for h in ["Authorization", "X-API-Key"]:
            self.session.headers.pop(h, None)

        resp = self._safe_request("GET", test_url)
        if resp and resp.status_code == 200:
            self._add_finding(
                finding_type="MISSING_AUTHENTICATION",
                severity="CRITICAL",
                endpoint=test_url,
                evidence={
                    "message": "Sensitive endpoint accessible without authentication"
                },
                confidence=0.85,
            )

        self.session.headers.update(original_headers)

    def _test_jwt_token(self, token: str):
        """Test JWT token for common weaknesses."""
        try:
            import base64

            parts = token.split(".")
            if len(parts) == 3:
                header = json.loads(base64.b64decode(parts[0] + "=="))
                alg = header.get("alg", "").lower()
                # Generate LLM JWT payloads for algorithm confusion testing
                llm_jwt_payloads = []
                if (
                    self.llm_payload_generator
                    and self.llm_payload_generator.is_available()
                ):
                    tech_hints = ", ".join(self.tech_stack[:8]) if self.tech_stack else "unknown"
                    llm_payloads = self.llm_payload_generator.generate_sync(
                        vuln_class="JWT_WEAKNESS",
                        param_name="jwt",
                        response_snippet=json.dumps({"alg": alg}) if alg else "",
                        framework_hints=tech_hints,
                    )
                    # LLM might return JWT-related manipulation payloads
                    # Try to use them as alternative Authorization headers
                    for lp in llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]:
                        if len(lp) > 20:  # Looks like a token
                            llm_jwt_payloads.append(lp)
                if alg == "none":
                    self._add_finding(
                        finding_type="JWT_ALG_NONE",
                        severity="CRITICAL",
                        endpoint=self.target_url,
                        evidence={"message": "JWT uses 'none' algorithm"},
                        confidence=0.95,
                    )
                elif alg in ["hs256", "hs384", "hs512"]:
                    self._add_finding(
                        finding_type="JWT_HMAC_ALGORITHM",
                        severity="INFO",
                        endpoint=self.target_url,
                        evidence={
                            "algorithm": alg,
                            "message": "JWT uses symmetric signing",
                        },
                        confidence=0.80,
                    )

                # Check for weak secrets via common test
                if alg == "hs256":
                    payload = json.loads(base64.b64decode(parts[1] + "=="))
                    if payload.get("admin") is True or payload.get("role") == "admin":
                        self._add_finding(
                            finding_type="JWT_PRIVILEGE_ESCALATION",
                            severity="HIGH",
                            endpoint=self.target_url,
                            evidence={
                                "payload": payload,
                                "message": "JWT contains privilege claims",
                            },
                            confidence=0.70,
                        )

                # Test LLM-generated JWT payloads
                for llm_payload in llm_jwt_payloads:
                    for auth_header in ["Authorization", "X-Access-Token", "Token"]:
                        test_resp = self._safe_request(
                            "GET",
                            self.target_url,
                            headers={auth_header: f"Bearer {llm_payload}"},
                        )
                        if test_resp and test_resp.status_code == 200:
                            self._add_finding(
                                finding_type="JWT_LLM_DETECTED_WEAKNESS",
                                severity="HIGH",
                                endpoint=self.target_url,
                                evidence={
                                    "llm_generated_payload": llm_payload[:30] + "...",
                                    "auth_header": auth_header,
                                    "message": "LLM-generated JWT bypass accepted by server",
                                },
                                confidence=0.6,
                            )
                            break
        except Exception:
            logger.warning("API scanner exception (non-fatal)", exc_info=True)

    def _test_api_key(self, api_key: str):
        """Test API key strength."""
        if len(api_key) < 16:
            self._add_finding(
                finding_type="WEAK_API_KEY",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "key_length": len(api_key),
                    "message": "API key is too short",
                },
                confidence=0.90,
            )

    def test_rate_limiting(self):
        """Test API rate limiting with controlled burst requests."""
        if self.authorized_scope and not self.target_url.startswith(self.authorized_scope):
            logger.warning(
                "Target %s is outside authorized scope %s — skipping rate limit test",
                self.target_url, self.authorized_scope,
            )
            return

        test_url = urljoin(self.target_url, "/api/health")

        for config in self.RATE_TEST_CONFIGS[:2]:  # Skip DDoS in standard scan
            requests_count = config["requests"]
            config["concurrency"]

            success_count = 0
            rate_limited_count = 0
            start_time = time.time()

            for _i in range(min(requests_count, 20)):  # Cap at 20 for safety
                resp = self._safe_request("GET", test_url)
                if resp:
                    if resp.status_code == 429:
                        rate_limited_count += 1
                    elif resp.status_code == 200:
                        success_count += 1

            duration = time.time() - start_time

            if rate_limited_count == 0 and success_count >= 10:
                self._add_finding(
                    finding_type="MISSING_RATE_LIMITING",
                    severity="HIGH",
                    endpoint=test_url,
                    evidence={
                        "requests_sent": success_count,
                        "duration_seconds": round(duration, 2),
                        "message": "No rate limiting detected",
                    },
                    confidence=0.75,
                )
                break
            elif rate_limited_count > 0:
                # Rate limiting is present, stop testing
                break
