"""
Web Scanner Tool - Scans web applications for vulnerabilities and security issues.
Includes WAF detection, katana integration, and injection testing capabilities.
"""

import time
import subprocess
import json
import re
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
import requests
from urllib.parse import urlparse, parse_qs, quote

SQL_TIME_PAYLOADS = [
    "1' AND SLEEP(5)--",
    "1' AND (SELECT * FROM (SELECT(SLEEP(5)))--",
    "1; WAITFOR DELAY '00:00:05'--",
    "1 AND BENCHMARK(5000000,MD5('test'))--",
]

CMD_TIME_PAYLOADS = [
    "; sleep 5",
    "| sleep 5",
    "`sleep 5`",
    "$(sleep 5)",
]

    
class PerEndpointRateLimiter:
    def __init__(self, default_rps=10):
        self.default_rps = default_rps
        self.endpoint_stats = defaultdict(lambda: {'requests': [], 'last_request': 0})
        self.endpoint_limits = {}  # Per-endpoint custom limits
    
    def set_limit(self, endpoint, requests_per_second):
        """Set custom rate limit for an endpoint."""
        self.endpoint_limits[endpoint] = requests_per_second
    
    def can_request(self, endpoint):
        """Check if we can make a request to this endpoint."""
        limit = self.endpoint_limits.get(endpoint, self.default_rps)
        now = time.time()
        stats = self.endpoint_stats[endpoint]
        
        # Clean old requests (keep last 60 seconds)
        stats['requests'] = [t for t in stats['requests'] if now - t < 60]
        
        # Check if under limit
        if len(stats['requests']) >= limit * 60:  # requests in last minute
            return False
        return True
    
    def record_request(self, endpoint):
        """Record a request to this endpoint."""
        self.endpoint_stats[endpoint]['requests'].append(time.time())


def detect_waf(response, target_url):
    """
    Detect Web Application Firewall presence.
    Returns: (waf_detected: bool, waf_type: str, details: dict)
    """
    waf_indicators = {
        'cloudflare': ['cf-ray', 'cloudflare', '__cfduid'],
        'aws_waf': ['x-aws-waf', 'aws-waf'],
        'f5_bigip': ['bigipserver', 'f5'],
        'mod_security': ['mod_security', 'secureflag'],
        'incapsula': ['incapsula', 'visid_incap'],
        'sucuri': ['sucuri', 'cloudproxy'],
        'akamai': ['akamai', 'x-akamai'],
    }

    headers = {k.lower(): str(v).lower() for k, v in response.headers.items()}
    body = response.text.lower()

    detected = False
    waf_type = None
    details = {}

    # Check headers
    for waf, indicators in waf_indicators.items():
        for indicator in indicators:
            if indicator in str(headers) or indicator in body:
                detected = True
                waf_type = waf
                details['indicator'] = indicator
                break
        if detected:
            break

    # Check for blocked content patterns
    blocked_patterns = [
        'access denied', 'blocked', 'forbidden',
        'security violation', 'request rejected'
    ]
    if any(p in body for p in blocked_patterns):
        details['blocked_content'] = True

    return detected, waf_type, details


def run_katana_crawl(target_url: str, timeout: int = 60) -> List[Dict[str, Any]]:
    """
    Run katana crawler and return discovered parameters.
    
    Args:
        target_url: Target URL to crawl
        timeout: Timeout in seconds for katana execution
        
    Returns:
        List of discovered parameters in format:
        [{'url': '...', 'method': 'GET', 'params': [{'name': '...', 'value': '...'}]}]
    """
    discovered_params = []
    
    try:
        # Run katana with JSON output for easy parsing
        cmd = [
            'katana', '-u', target_url,
            '-json', '-silent',
            '-depth', '2',
            '-kf', 'all',  # Include forms
            '-timeout', str(timeout)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 10
        )
        
        # Parse katana JSON output
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                data = json.loads(line)
                url = data.get('url', '')
                method = data.get('method', 'GET')
                
                # Extract parameters from URL
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                
                param_list = []
                for name, values in params.items():
                    param_list.append({
                        'name': name,
                        'value': values[0] if values else ''
                    })
                
                # Also check for form inputs if present in katana output
                if 'inputs' in data:
                    for inp in data['inputs']:
                        param_list.append({
                            'name': inp.get('name', ''),
                            'value': inp.get('value', ''),
                            'type': inp.get('type', 'text')
                        })
                
                if param_list or method != 'GET':
                    discovered_params.append({
                        'url': url,
                        'method': method,
                        'params': param_list
                    })
                    
            except json.JSONDecodeError:
                continue
                
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Katana not installed or timed out
        pass
    
    return discovered_params


# SQL Injection payloads
SQLI_PAYLOADS = [
    "' OR '1'='1",
    "' OR 1=1--",
    "' UNION SELECT NULL--",
    "1' AND 1=1--",
    "1' AND 1=2--",
    "admin' --",
    "admin' #",
    "' OR 'x'='x",
]

# XSS payloads
XSS_PAYLOADS = [
    '<script>alert(1)</script>',
    '"><script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
    '<svg onload=alert(1)>',
]

# Error patterns indicating SQL injection
SQLI_ERROR_PATTERNS = [
    r'mysql_fetch',
    r'mysql_',
    r'sql syntax',
    r'warning: mysql',
    r'postgresql.*error',
    r'ora[0-9][0-9][0-9]',
    r'microsoft ole db',
    r'odbc sql server',
    r'syntax error',
    r'unclosed quotation mark',
]


def analyze_status_code(status_code, response_text):
    """Analyze HTTP status code and response."""
    analysis = {
        'status': status_code,
        'category': None,
        'anomaly': False,
        'details': []
    }
    
    if status_code == 200:
        analysis['category'] = 'success'
    elif status_code == 401:
        analysis['category'] = 'unauthorized'
        analysis['anomaly'] = True
    elif status_code == 403:
        analysis['category'] = 'forbidden'
    elif status_code == 404:
        analysis['category'] = 'not_found'
    elif status_code >= 500:
        analysis['category'] = 'server_error'
        analysis['anomaly'] = True
        analysis['details'].append('Server error detected')
    
    return analysis


def analyze_content_type(headers):
    content_type = headers.get('content-type', '').lower()
    analysis = {
        'content_type': content_type,
        'type': None,
        'charset': None,
        'anomaly': False
    }
    
    if 'application/json' in content_type:
        analysis['type'] = 'json'
    elif 'text/html' in content_type:
        analysis['type'] = 'html'
    elif 'application/xml' in content_type or 'text/xml' in content_type:
        analysis['type'] = 'xml'
    
    # Extract charset
    if 'charset=' in content_type:
        analysis['charset'] = content_type.split('charset=')[1].strip()
    
    return analysis


def analyze_response_size(response):
    size = len(response.content)
    analysis = {
        'size': size,
        'size_category': 'normal',
        'anomaly': False
    }
    
    if size == 0:
        analysis['size_category'] = 'empty'
        analysis['anomaly'] = True
    elif size < 100:
        analysis['size_category'] = 'very_small'
    elif size > 1000000:  # > 1MB
        analysis['size_category'] = 'very_large'
    
    return analysis


def fingerprint_technology(headers, response_text):
    """Detect web technologies from headers and response."""
    tech = {
        'server': headers.get('server', ''),
        'x-powered-by': headers.get('x-powered-by', ''),
        'frameworks': [],
        'cdn': None,
    }
    
    # Detect CDN
    cdn_headers = ['cf-ray', 'x-sucuri-id', 'x-akamai-transformed']
    for h in cdn_headers:
        if h in headers:
            tech['cdn'] = h.replace('x-', '').replace('-', ' ').title()
            break
    
    # Detect frameworks (simple pattern matching)
    if 'laravel' in response_text.lower():
        tech['frameworks'].append('Laravel')
    if 'django' in response_text.lower():
        tech['frameworks'].append('Django')
    if 'express' in response_text.lower() or 'node' in headers.get('x-powered-by', '').lower():
        tech['frameworks'].append('Express/Node.js')
    
    return tech


def check_time_based_injection(target: str, param: str, payload: str, base_time: float) -> Tuple[bool, float]:
    """Test for time-based blind vulnerabilities."""
    start = time.time()
    try:
        response = requests.get(target, params={param: payload}, timeout=30)
    except requests.RequestException:
        return False, 0.0
    elapsed = time.time() - start
    
    # If response time > base_time + 4 seconds threshold
    if elapsed > base_time + 4:
        return True, elapsed
    return False, elapsed


class WebScanner:
    """Main web scanner class with WAF detection and injection testing."""

    def __init__(self, target_url: str, timeout: int = 30, scan_config: Optional[Dict[str, Any]] = None):
        self.target_url = target_url
        self.timeout = timeout
        self.scan_config = scan_config or {}
        self.waf_info: Optional[Dict[str, Any]] = None
        self.scan_metadata: Dict[str, Any] = {}
        self.findings: List[Dict[str, Any]] = []
        self.base_time: float = 0.0
        self.discovered_params: List[Dict[str, Any]] = []
        default_rps = self.scan_config.get('requests_per_second', 10)
        self.rate_limiter = PerEndpointRateLimiter(default_rps=default_rps)
    
    def _rate_limited_request(self, method: str, endpoint: str, **kwargs):
        """Make a rate-limited HTTP request."""
        while not self.rate_limiter.can_request(endpoint):
            time.sleep(0.1)
        method = method.lower()
        if method == 'get':
            response = requests.get(endpoint, **kwargs)
        elif method == 'post':
            response = requests.post(endpoint, **kwargs)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        self.rate_limiter.record_request(endpoint)
        return response

    def scan(self, run_crawl: bool = True) -> Dict[str, Any]:
        """
        Run the web scan with WAF detection and injection tests.
        
        Args:
            run_crawl: Whether to run katana crawl first (default True)
            
        Returns:
            Scan results with findings
        """
        result = {
            'target_url': self.target_url,
            'findings': [],
            'metadata': {}
        }

        try:
            # Initial connection to check for WAF and measure baseline time
            start = time.time()
            response = self._rate_limited_request('get', self.target_url, timeout=self.timeout)
            self.base_time = time.time() - start
            self.scan_metadata['base_response_time'] = self.base_time

            # WAF Detection
            waf_detected, waf_type, waf_details = detect_waf(response, self.target_url)

            # Include WAF info in scan metadata
            self.scan_metadata['waf'] = {
                'detected': waf_detected,
                'type': waf_type,
                'details': waf_details
            }

            if waf_detected:
                print(f"[WAF] Detected: {waf_type}")
            else:
                print("[WAF] No WAF detected")

            self.waf_info = {
                'detected': waf_detected,
                'type': waf_type,
                'details': waf_details
            }

            # Run katana crawl to discover parameters
            if run_crawl:
                print("[*] Running katana crawl to discover parameters...")
                self.discovered_params = run_katana_crawl(self.target_url)
                print(f"[*] Discovered {len(self.discovered_params)} URLs with parameters")

            # Run injection tests with discovered parameters
            self.test_sql_injection()
            self.test_xss_injection()
            self.test_time_based_injections()

            result['findings'] = self.findings
            result['metadata'] = self.scan_metadata
            result['metadata']['discovered_params_count'] = len(self.discovered_params)

        except requests.RequestException as e:
            result['error'] = str(e)

        return result

    def test_sql_injection(self, discovered_params: Optional[List[Dict]] = None) -> None:
        """
        Test for SQL injection vulnerabilities.
        
        Args:
            discovered_params: Optional list of discovered parameters from katana.
                             If not provided, uses self.discovered_params.
        """
        params_to_test = discovered_params or self.discovered_params
        
        # Build test cases from discovered params
        test_cases = []
        
        if params_to_test:
            for endpoint in params_to_test:
                url = endpoint['url']
                for param in endpoint.get('params', []):
                    param_name = param.get('name')
                    if not param_name:
                        continue
                    for payload in SQLI_PAYLOADS:
                        test_cases.append({
                            'url': url,
                            'param': param_name,
                            'payload': payload,
                            'method': endpoint.get('method', 'GET')
                        })
        else:
            # Fallback: test common parameters on target URL
            fallback_params = ['id', 'user', 'username', 'query', 'search', 'q']
            for param in fallback_params:
                for payload in SQLI_PAYLOADS[:3]:  # Limit payloads for fallback
                    test_cases.append({
                        'url': self.target_url,
                        'param': param,
                        'payload': payload,
                        'method': 'GET'
                    })
        
        # Run test cases
        for test in test_cases:
            try:
                url = test['url']
                param = test['param']
                payload = test['payload']
                method = test['method']
                
                if method.upper() == 'GET':
                    test_url = f"{url}?{param}={quote(payload)}"
                    resp = self._rate_limited_request('get', test_url, timeout=self.timeout, verify=False)
                else:
                    resp = self._rate_limited_request('post', url, data={param: payload}, timeout=self.timeout, verify=False)
                
                if not resp:
                    continue
                
                # Check for SQL error patterns in response
                body_lower = resp.text.lower()
                for pattern in SQLI_ERROR_PATTERNS:
                    if re.search(pattern, body_lower, re.IGNORECASE):
                        finding = {
                            'type': 'SQL_INJECTION',
                            'severity': 'HIGH',
                            'endpoint': test['url'],
                            'evidence': {
                                'parameter': param,
                                'payload': payload,
                                'error_pattern': pattern,
                                'method': method,
                            }
                        }
                        self.add_finding(finding)
                        break
                        
            except (requests.RequestException, KeyError):
                continue

    def test_xss_injection(self, discovered_params: Optional[List[Dict]] = None) -> None:
        """
        Test for XSS vulnerabilities.
        
        Args:
            discovered_params: Optional list of discovered parameters from katana.
                             If not provided, uses self.discovered_params.
        """
        params_to_test = discovered_params or self.discovered_params
        
        test_cases = []
        
        if params_to_test:
            for endpoint in params_to_test:
                url = endpoint['url']
                for param in endpoint.get('params', []):
                    param_name = param.get('name')
                    if not param_name:
                        continue
                    for payload in XSS_PAYLOADS:
                        test_cases.append({
                            'url': url,
                            'param': param_name,
                            'payload': payload,
                            'method': endpoint.get('method', 'GET')
                        })
        else:
            # Fallback: test for reflected XSS on target
            for payload in XSS_PAYLOADS[:2]:
                test_url = f"{self.target_url}?q={quote(payload)}"
                try:
                    resp = self._rate_limited_request('get', test_url, timeout=self.timeout, verify=False)
                    if resp and payload in resp.text and '<script>' in resp.text:
                        finding = {
                            'type': 'REFLECTED_XSS',
                            'severity': 'MEDIUM',
                            'endpoint': test_url,
                            'evidence': {
                                'payload': payload,
                                'reflected': True,
                            }
                        }
                        self.add_finding(finding)
                except requests.RequestException:
                    continue
        
        # Run test cases for discovered params
        for test in test_cases:
            try:
                url = test['url']
                param = test['param']
                payload = test['payload']
                
                test_url = f"{url}?{param}={quote(payload)}"
                resp = self._rate_limited_request('get', test_url, timeout=self.timeout, verify=False)
                
                if resp and payload in resp.text:
                    # Check if script actually executes (not just reflected)
                    if '<script>' in resp.text or 'onerror=' in resp.text:
                        finding = {
                            'type': 'REFLECTED_XSS',
                            'severity': 'HIGH',
                            'endpoint': test_url,
                            'evidence': {
                                'parameter': param,
                                'payload': payload,
                                'reflected_unencoded': True,
                            }
                        }
                        self.add_finding(finding)
                        
            except requests.RequestException:
                continue

    def test_time_based_injections(self, discovered_params: Optional[List[Dict]] = None) -> None:
        """Scan for time-based SQL and command injection vulnerabilities."""
        if self.base_time == 0:
            return
        
        params_to_test = discovered_params or self.discovered_params
        if not params_to_test:
            return

        for endpoint in params_to_test:
            url = endpoint['url']
            for param in endpoint.get('params', []):
                param_name = param.get('name')
                if not param_name:
                    continue

                # Test SQL time-based payloads
                for payload in SQL_TIME_PAYLOADS:
                    injected, elapsed = check_time_based_injection(
                        url, param_name, payload, self.base_time
                    )
                    if injected:
                        finding = {
                            'type': 'TIME_BASED_SQLI',
                            'severity': 'HIGH',
                            'endpoint': url,
                            'parameter': param_name,
                            'payload': payload,
                            'response_time': elapsed,
                            'base_time': self.base_time,
                            'message': f'Time-based SQL injection detected on {param_name}'
                        }
                        self.add_finding(finding)

                # Test command injection time-based payloads
                for payload in CMD_TIME_PAYLOADS:
                    injected, elapsed = check_time_based_injection(
                        url, param_name, payload, self.base_time
                    )
                    if injected:
                        finding = {
                            'type': 'TIME_BASED_CMDI',
                            'severity': 'HIGH',
                            'endpoint': url,
                            'parameter': param_name,
                            'payload': payload,
                            'response_time': elapsed,
                            'base_time': self.base_time,
                            'message': f'Time-based command injection detected on {param_name}'
                        }
                        self.add_finding(finding)

    def add_finding(self, finding: Dict[str, Any]) -> None:
        """Add a finding, automatically tagging with WAF info if detected."""
        if self.waf_info and self.waf_info['detected']:
            finding['waf_interference'] = True
            finding['waf_type'] = self.waf_info['type']
        self.findings.append(finding)


if __name__ == '__main__':
    # Example usage
    scanner = WebScanner('https://example.com')
    result = scanner.scan()
    print(json.dumps(result, indent=2))
