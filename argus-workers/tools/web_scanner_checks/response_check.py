"""
Response analysis: WAF detection, time-based detection, response analysis, differential analysis.
"""
import json
import logging
import re
import time

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

WAF_TRIGGER_PAYLOADS = [
    "' OR 1=1--",
    "<script>alert(1)</script>",
    "../../etc/passwd",
    " UNION SELECT * FROM users--",
]

WAF_SIGNATURES = {
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

TIME_SQLI_PAYLOADS = [
    ("mysql", "' OR SLEEP(5)--"),
    ("postgres", "'; SELECT pg_sleep(5)--"),
    ("mssql", "'; WAITFOR DELAY '0:0:5'--"),
    ("sqlite", "' AND randomblob(500000000)--"),
    ("oracle", "' AND 1=DBMS_PIPE.RECEIVE_MESSAGE('RDS',5)--"),
]

TIME_CMDI_PAYLOADS = [
    ("; sleep", "; sleep 5"),
    ("| sleep", "| sleep 5"),
    ("&& sleep", "&& sleep 5"),
    ("`sleep", "`sleep 5`"),
    ("$(sleep", "$(sleep 5)"),
]

STACK_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"at [\w\.]+\.[\w]+\([^)]*\)",
    r"Exception in thread",
    r"Fatal error:",
    r"PHP Stack trace:",
    r"in /[\w/]+ on line \d+",
]

DEBUG_INDICATORS = [
    "DEBUG = True",
    "debug mode",
    "debug toolbar",
    "flask-debug",
    "django-debug",
]


def run_check(target_url: str, session, findings: list) -> list[dict]:
    _detect_waf(target_url, session, findings)
    _time_based_detection(target_url, session, findings)
    _response_analysis(target_url, session, findings)
    _differential_analysis(target_url, session, findings)
    return findings


def _detect_waf(target_url, session, findings):
    waf_response = None
    for payload in WAF_TRIGGER_PAYLOADS:
        test_url = f"{target_url}?test={payload}"
        resp = safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp:
            continue
        if resp.status_code in (403, 406, 419, 423, 501):
            waf_response = resp
            break
    if not waf_response:
        resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if resp:
            waf_response = resp
    if not waf_response:
        return
    headers_str = str(waf_response.headers).lower()
    body_str = waf_response.text.lower()
    detected_wafs = set()
    for waf_name, signatures in WAF_SIGNATURES.items():
        for sig_type, sig_value in signatures:
            sig_value_lower = str(sig_value).lower()
            if (sig_type == "header" and sig_value_lower in headers_str) or \
               (sig_type == "body" and sig_value_lower in body_str) or \
               (sig_type == "status" and waf_response.status_code == sig_value):
                detected_wafs.add(waf_name)
    if detected_wafs:
        findings.append(make_finding("WAF_DETECTED", "INFO", target_url, {
            "waf_types": list(detected_wafs),
            "trigger_status": waf_response.status_code,
            "response_headers": dict(waf_response.headers),
        }, 0.8))
    elif waf_response.status_code in (403, 406, 419, 423):
        findings.append(make_finding("WAF_DETECTED", "INFO", target_url, {
            "waf_types": ["Unknown"],
            "trigger_status": waf_response.status_code,
            "message": "Blocking behavior detected but WAF type not identified",
        }, 0.5))


def _time_based_detection(target_url, session, findings):
    threshold = 4.0
    for db_type, payload in TIME_SQLI_PAYLOADS:
        test_url = f"{target_url}?id={payload}"
        start = time.time()
        safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        elapsed = time.time() - start
        if elapsed >= threshold:
            findings.append(make_finding("TIME_BASED_SQL_INJECTION", "HIGH", test_url, {
                "db_type_tested": db_type,
                "payload": payload,
                "response_time_seconds": elapsed,
                "threshold_seconds": threshold,
                "message": f"Response delayed by {elapsed:.1f}s suggests time-based SQL injection",
            }, 0.7))
            break
    for cmd_type, payload in TIME_CMDI_PAYLOADS:
        test_url = f"{target_url}?input={payload}"
        start = time.time()
        safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        elapsed = time.time() - start
        if elapsed >= threshold:
            findings.append(make_finding("TIME_BASED_COMMAND_INJECTION", "HIGH", test_url, {
                "payload_type": cmd_type,
                "payload": payload,
                "response_time_seconds": elapsed,
                "threshold_seconds": threshold,
                "message": f"Response delayed by {elapsed:.1f}s suggests command injection",
            }, 0.7))
            break
    xxe_payload = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "http://127.0.0.1:9999/xxe">]><foo>&xxe;</foo>'
    start = time.time()
    safe_request("POST", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                 data=xxe_payload, headers={"Content-Type": "application/xml"})
    elapsed = time.time() - start
    if elapsed >= threshold:
        findings.append(make_finding("BLIND_XXE", "HIGH", target_url, {
            "payload": xxe_payload[:100],
            "response_time_seconds": elapsed,
            "threshold_seconds": threshold,
            "message": "Long response time may indicate OOB XXE resolution attempt",
        }, 0.4))


def _response_analysis(target_url, session, findings):
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not resp:
        return

    server_header = resp.headers.get("Server", "")
    powered_by = resp.headers.get("X-Powered-By", "")
    asp_version = resp.headers.get("X-AspNet-Version", "")
    asp_mvc = resp.headers.get("X-AspNetMvc-Version", "")

    if server_header:
        findings.append(make_finding("SERVER_INFO_DISCLOSURE", "LOW", target_url, {
            "header": "Server", "value": server_header,
            "message": "Server software version exposed",
        }, 0.9))
    if powered_by:
        findings.append(make_finding("FRAMEWORK_VERSION_LEAK", "LOW", target_url, {
            "header": "X-Powered-By", "value": powered_by,
            "message": "Framework version exposed",
        }, 0.9))
    if asp_version or asp_mvc:
        findings.append(make_finding("FRAMEWORK_VERSION_LEAK", "LOW", target_url, {
            "headers": {"X-AspNet-Version": asp_version, "X-AspNetMvc-Version": asp_mvc},
            "message": "ASP.NET version information exposed",
        }, 0.9))

    for pattern in STACK_PATTERNS:
        match = re.search(pattern, resp.text, re.IGNORECASE)
        if match:
            snippet = resp.text[max(0, match.start() - 100):match.end() + 200]
            findings.append(make_finding("STACK_TRACE_EXPOSURE", "MEDIUM", target_url, {
                "pattern_matched": pattern, "snippet": snippet,
                "message": "Stack trace or debug information exposed in response",
            }, 0.8))
            break

    internal_ip_pattern = r"(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})"
    internal_ips = re.findall(internal_ip_pattern, resp.text)
    if internal_ips:
        findings.append(make_finding("INTERNAL_IP_DISCLOSURE", "LOW", target_url, {
            "internal_ips_found": list(set(internal_ips)),
            "message": "Internal IP addresses exposed in response",
        }, 0.8))

    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    emails = re.findall(email_pattern, resp.text)
    if emails:
        findings.append(make_finding("EMAIL_DISCLOSURE", "INFO", target_url, {
            "emails_found": list(set(emails))[:10],
            "count": len(set(emails)),
            "message": "Email addresses exposed in response",
        }, 0.7))

    for indicator in DEBUG_INDICATORS:
        if indicator.lower() in resp.text.lower():
            findings.append(make_finding("DEBUG_MODE_ENABLED", "MEDIUM", target_url, {
                "indicator": indicator,
                "message": "Debug mode may be enabled",
            }, 0.7))
            break


def _differential_analysis(target_url, session, findings):
    baseline = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not baseline:
        return
    baseline_status = baseline.status_code
    baseline_len = len(baseline.text)
    baseline_time = baseline.elapsed.total_seconds()

    test_cases = [
        {"name": "method_override_get", "method": "POST", "url": target_url,
         "headers": {"X-HTTP-Method-Override": "GET"}, "data": ""},
        {"name": "method_override_delete", "method": "POST", "url": target_url,
         "headers": {"X-HTTP-Method-Override": "DELETE"}, "data": ""},
        {"name": "parameter_pollution", "method": "GET", "url": f"{target_url}?id=1&id=2&id=3",
         "headers": {}},
        {"name": "null_byte_injection", "method": "GET", "url": f"{target_url}?file=test.txt%00.jpg",
         "headers": {}},
        {"name": "large_content_length", "method": "POST", "url": target_url,
         "headers": {"Content-Length": "999999999"}, "data": "x"},
    ]

    for test in test_cases:
        try:
            kwargs = {"headers": test.get("headers", {})}
            if "data" in test:
                kwargs["data"] = test["data"]
            resp = safe_request(test["method"], test["url"], session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                                **kwargs)
            if not resp:
                continue
            status_diff = resp.status_code != baseline_status
            len_diff = abs(len(resp.text) - baseline_len) > 100
            time_diff = abs(resp.elapsed.total_seconds() - baseline_time) > 2
            if status_diff or len_diff or time_diff:
                findings.append(make_finding("DIFFERENTIAL_ANOMALY", "MEDIUM", test["url"], {
                    "test_name": test["name"],
                    "baseline_status": baseline_status,
                    "modified_status": resp.status_code,
                    "baseline_length": baseline_len,
                    "modified_length": len(resp.text),
                    "baseline_time": baseline_time,
                    "modified_time": resp.elapsed.total_seconds(),
                    "headers_sent": test.get("headers", {}),
                }, 0.6))
        except Exception:
            logger.debug(f"Differential test failed: {test['name']}")


class ResponseCheck:
    def __init__(self):
        self.name = "response"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
