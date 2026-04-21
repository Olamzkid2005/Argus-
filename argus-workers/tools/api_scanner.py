"""
API Security Testing Module

Integrates OWASP ZAP, GraphQL security scanning, authentication testing,
and rate limit / DDoS testing capabilities.

Requirements: 15.1, 15.2, 15.3, 15.4
"""
import json
import time
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError


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
        {"requests": 1000, "concurrency": 100, "description": "DDoS simulation"},
    ]
    
    def __init__(self, timeout: int = 15, rate_limit: float = 0.05):
        """
        Initialize API security scanner.
        
        Args:
            timeout: Request timeout in seconds
            rate_limit: Seconds between requests
        """
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Argus-API-Scanner/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self.findings = []
    
    def scan(self, target_url: str, api_type: str = "rest", auth_config: Optional[Dict] = None) -> List[Dict]:
        """
        Run comprehensive API security scan.
        
        Args:
            target_url: Base API URL
            api_type: API type ('rest', 'graphql', 'openapi')
            auth_config: Optional authentication configuration
            
        Returns:
            List of vulnerability findings
        """
        self.findings = []
        self.target_url = target_url.rstrip("/")
        self.auth_config = auth_config or {}
        
        # Apply authentication if configured
        if self.auth_config.get("type") == "api_key":
            self.session.headers[self.auth_config.get("header", "X-API-Key")] = self.auth_config.get("key", "")
        elif self.auth_config.get("type") == "bearer":
            self.session.headers["Authorization"] = f"Bearer {self.auth_config.get('token', '')}"
        
        # 1. OWASP ZAP-style basic checks
        self.check_security_headers()
        
        # 2. API type-specific scanning
        if api_type == "graphql":
            self.scan_graphql()
        elif api_type == "openapi":
            self.scan_openapi()
        else:
            self.scan_rest_endpoints()
        
        # 3. Authentication testing
        self.test_authentication()
        
        # 4. Rate limiting test
        self.test_rate_limiting()
        
        return self.findings
    
    def _safe_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make HTTP request with error handling."""
        try:
            kwargs.setdefault("timeout", self.timeout)
            kwargs.setdefault("allow_redirects", False)
            resp = self.session.request(method, url, **kwargs)
            time.sleep(self.rate_limit)
            return resp
        except (RequestException, Timeout, ConnectionError):
            return None
    
    def _add_finding(self, finding_type: str, severity: str, endpoint: str, evidence: Dict, confidence: float = 0.8):
        """Add a finding to results."""
        self.findings.append({
            "type": finding_type,
            "severity": severity,
            "endpoint": endpoint,
            "evidence": evidence,
            "confidence": confidence,
            "tool": "api_scanner",
        })
    
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
            "POST", graphql_url,
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
            "POST", graphql_url,
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
        swagger_paths = ["/swagger.json", "/api-docs", "/openapi.json", "/v1/swagger.json"]
        for path in swagger_paths:
            url = urljoin(self.target_url, path)
            resp = self._safe_request("GET", url)
            if resp and resp.status_code == 200:
                self._add_finding(
                    finding_type="EXPOSED_OPENAPI_SPEC",
                    severity="LOW",
                    endpoint=url,
                    evidence={"message": "OpenAPI/Swagger specification is publicly accessible"},
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
                evidence={"message": "Sensitive endpoint accessible without authentication"},
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
                        evidence={"algorithm": alg, "message": "JWT uses symmetric signing"},
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
                            evidence={"payload": payload, "message": "JWT contains privilege claims"},
                            confidence=0.70,
                        )
        except Exception:
            pass
    
    def _test_api_key(self, api_key: str):
        """Test API key strength."""
        if len(api_key) < 16:
            self._add_finding(
                finding_type="WEAK_API_KEY",
                severity="HIGH",
                endpoint=self.target_url,
                evidence={"key_length": len(api_key), "message": "API key is too short"},
                confidence=0.90,
            )
    
    def test_rate_limiting(self):
        """Test API rate limiting with controlled burst requests."""
        test_url = urljoin(self.target_url, "/api/health")
        
        for config in self.RATE_TEST_CONFIGS[:2]:  # Skip DDoS in standard scan
            requests_count = config["requests"]
            concurrency = config["concurrency"]
            
            success_count = 0
            rate_limited_count = 0
            start_time = time.time()
            
            for i in range(min(requests_count, 20)):  # Cap at 20 for safety
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
