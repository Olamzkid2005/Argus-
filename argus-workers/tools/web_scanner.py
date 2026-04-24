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
import time
import re
import json
import base64
import logging
from typing import Dict, List, Optional
from urllib.parse import urlparse, urljoin
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

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
    
    def __init__(self, timeout: int = 10, rate_limit: float = 0.1):
        """
        Initialize web scanner.
        
        Args:
            timeout: Request timeout in seconds
            rate_limit: Seconds between requests
        """
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        self.findings = []
    
    def scan(self, target_url: str) -> List[Dict]:
        """
        Run comprehensive scan against target.
        
        Args:
            target_url: Target URL to scan
            
        Returns:
            List of vulnerability findings
        """
        self.findings = []
        self.target_url = target_url.rstrip("/")
        
        logger.info(f"Starting comprehensive web scan: {self.target_url}")
        
        # 1. Security headers audit
        self.check_security_headers()
        
        # 2. CSP analysis
        self.check_csp()
        
        # 3. Cookie security
        self.check_cookies()
        
        # 4. CORS analysis
        self.check_cors()
        
        # 5. Sensitive file detection
        self.check_sensitive_files()
        
        # 6. JS secret scanning
        self.check_js_secrets()
        
        # 7. Open redirect detection
        self.check_open_redirects()
        
        # 8. Host header injection
        self.check_host_header_injection()
        
        # 9. HTTP verb tampering
        self.check_verb_tampering()
        
        # 10. Debug endpoint detection
        self.check_debug_endpoints()
        
        # 11. Authentication testing
        self.check_auth_endpoints()
        
        # 12. Mass assignment testing
        self.check_mass_assignment()
        
        # 13. XSS testing (on discovered parameters)
        self.check_xss()
        
        # 14. SSTI testing
        self.check_ssti()
        
        # 15. LFI testing
        self.check_lfi()
        
        # 16. XXE testing
        self.check_xxe()
        
        # 17. GraphQL introspection
        self.check_graphql_introspection()
        
        # 18. JWT algorithm confusion
        self.check_jwt_algorithm_confusion()
        
        # 19. Prototype pollution
        self.check_prototype_pollution()
        
        # 20. Cache poisoning
        self.check_cache_poisoning()
        
        # 21. HTTP request smuggling
        self.check_http_request_smuggling()
        
        # 22. DOM XSS
        self.check_dom_xss()
        
        # 23. OpenAPI discovery
        self.check_openapi_discovery()
        
        logger.info(f"Scan complete: {len(self.findings)} findings")
        return self.findings
    
    def _safe_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make HTTP request with error handling."""
        try:
            kwargs.setdefault("timeout", self.timeout)
            kwargs.setdefault("allow_redirects", True)
            kwargs.setdefault("verify", False)  # Don't fail on self-signed certs
            resp = self.session.request(method, url, **kwargs)
            time.sleep(self.rate_limit)
            return resp
        except (RequestException, Timeout, ConnectionError) as e:
            logger.debug(f"Request failed: {e}")
            return None
    
    def _add_finding(self, finding_type: str, severity: str, endpoint: str, 
                     evidence: Dict, confidence: float = 0.8):
        """Add a finding to the results."""
        self.findings.append({
            "type": finding_type,
            "severity": severity,
            "endpoint": endpoint,
            "evidence": evidence,
            "confidence": confidence,
        })
    
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
        
        # Get Set-Cookie header - handle both single and multiple cookies
        cookie_header = resp.headers.get("Set-Cookie")
        if not cookie_header:
            return
        
        # Split multiple cookies (comma-separated in some implementations)
        cookies = cookie_header.split(",") if "," in cookie_header else [cookie_header]
        
        for cookie_str in cookies:
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
            severity = "CRITICAL" if acac.lower() == "true" else "HIGH"
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
        for js_url in js_urls[:10]:
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
            if resp and resp.status_code not in (405, 404, 403, 501):
                # TRACE method specifically is dangerous
                if method == "TRACE":
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
                for username, password in self.DEFAULT_CREDS[:3]:  # Limit to 3
                    login_resp = self._safe_request(
                        "POST", url,
                        data={"username": username, "password": password},
                        allow_redirects=False,
                    )
                    if login_resp and login_resp.status_code in (200, 302):
                        # Check if login was successful (redirect to dashboard, etc.)
                        location = login_resp.headers.get("Location", "").lower()
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
    
    def check_mass_assignment(self):
        """Check for mass assignment vulnerabilities."""
        api_paths = ["/api/v1/users", "/api/users", "/api/v1/accounts", "/api/accounts"]
        
        for path in api_paths:
            url = urljoin(self.target_url, path.lstrip("/"))
            
            for payload in self.MASS_ASSIGN_PAYLOADS[:2]:  # Limit to 2
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
        params = re.findall(r'[?&](\w+)=', resp.text)
        if not params:
            return
        
        # Only test inputs that look like they accept user data
        # Avoid testing navigation params
        ignore_params = ['redirect', 'next', 'url', 'dest', 'target', 'goto', 
                        'continue', 'return', 'ref', 'dest_url']
        
        for param in set(params[:5]):
            if param.lower() in ignore_params:
                continue
            
            for payload in self.XSS_PAYLOADS[:3]:
                test_url = f"{self.target_url}?{param}={payload}"
                test_resp = self._safe_request("GET", test_url)
                if not test_resp:
                    continue
                
                # Check if payload is reflected UNENCODED
                # This matters - <script> vs &lt;script&gt;
                if payload in test_resp.text:
                    # Only flag HIGH if it's in script context or event handler
                    # Not just reflected in HTML (which browsers escape)
                    is_script_context = "<script" in test_resp.text and "<script" in test_resp.text
                    
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
            # Test with SSTI payloads
            test_payloads = ['{{7*7}}', '${7*7}', '<%= 7*7 %>']
            for payload in test_payloads:
                test_url = f"{self.target_url}?{param}={payload}"
                test_resp = self._safe_request("GET", test_url)
                if not test_resp:
                    continue
                
                # Must see EVALUATION (49), not just reflection
                # Check for patterns like "49", " 49 ", or numeric 49 in context
                has_evaluation = " 49 " in test_resp.text or ">49<" in test_resp.text
                
                # Also verify it's NOT error or part of another word
                if has_evaluation:
                    # Do a sanity check - ensure it's actual output, not error message
                    if "error" not in test_resp.text.lower() and "undefined" not in test_resp.text.lower():
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
            for payload in self.LFI_PAYLOADS[:2]:
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
            parts = jwt_token.split(".")
            if len(parts) != 3:
                continue
            try:
                header = json.loads(base64.urlsafe_b64decode(parts[0] + "==").decode("utf-8"))
            except:
                continue
            
            # Test alg:none
            none_header = base64.urlsafe_b64encode(
                json.dumps({"alg": "none", "typ": "JWT"}).encode()
            ).decode().rstrip("=")
            none_jwt = f"{none_header}.{parts[1]}."
            
            for auth_header in ["Authorization", "X-Access-Token", "Token"]:
                test_resp = self._safe_request(
                    "GET", self.target_url,
                    headers={auth_header: f"Bearer {none_jwt}"}
                )
                if test_resp and test_resp.status_code == 200:
                    self._add_finding(
                        finding_type="JWT_ALGORITHM_CONFUSION",
                        severity="HIGH",
                        endpoint=self.target_url,
                        evidence={
                            "original_jwt": jwt_token[:20] + "...",
                            "test_algorithm": "none",
                            "auth_header": auth_header,
                            "message": "Server accepted JWT with alg:none",
                        },
                        confidence=0.7,
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
        dom_payloads = ["<img src=x onerror=alert(1)>", "<script>alert(1)</script>"]
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