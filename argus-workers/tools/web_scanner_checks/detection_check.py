"""
Detection of exposed debug endpoints, sensitive files, and verb tampering.
"""
import logging
import re
from urllib.parse import urljoin

from config.constants import LLM_MAX_GENERATED_PAYLOADS, RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

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

FILE_SIGNATURES = {
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

NOT_FOUND_PATTERNS = [
    "not found", "does not exist", "page not found",
    "return to", "go back", "homepage",
    "invalid url", "wrong url", "url not found",
    "nothing here", "no such page", "page does not",
]

HTML_SIGNATURES = [b"<!doctype html", b"<html", b"scroll-smooth"]

DEBUG_PATHS = [
    "/debug", "/_debug", "/console", "/actuator",
    "/actuator/env", "/actuator/health", "/__debug__",
    "/phpinfo.php", "/info.php", "/_profiler",
    "/server-status", "/.env",
]

DEBUG_SIGNATURES = {
    "/phpinfo.php": [b"php version", b"PHP_VERSION"],
    "/info.php": [b"php version", b"PHP_VERSION"],
    "/actuator/env": [b"spring", b"application", b"property"],
    "/actuator/health": [b"status", b"UP", b"DOWN"],
    "/actuator": [b"href", b"env", b"health"],
    "/server-status": [b"Server Status", b"Apache", b"nginx"],
}

HTML_DEBUG_SIGNATURES = [b"<!DOCTYPE html", b"<html", b"<!DOCTYPE", b"scroll-smooth"]


def run_check(target_url: str, session, findings: list) -> list[dict]:
    return DetectionCheck().check(target_url, session, findings)
def _check_debug_endpoints(target_url, session, findings):
    for path in DEBUG_PATHS:
        url = urljoin(target_url, path.lstrip("/"))
        resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp or resp.status_code != 200:
            continue
        content = resp.text
        if len(content) < 100:
            continue
        content_first100 = content[:100].lower().encode()
        if any(sig in content_first100 for sig in HTML_DEBUG_SIGNATURES):
            continue
        content_lower = content.lower()
        has_debug_content = any(
            indicator in content_lower
            for indicator in ["debug", "stack trace", "exception", "phpinfo", "profiler", "actuator"]
        )
        signatures = DEBUG_SIGNATURES.get(path, [])
        if signatures:
            content_bytes = content.encode('utf-8', errors='ignore')
            has_signature = any(sig in content_bytes for sig in signatures)
        else:
            has_signature = has_debug_content
        is_console = "function" in content_lower and "eval" in content_lower
        if has_debug_content or has_signature or is_console:
            confidence = 0.9 if (signatures or has_debug_content) else 0.7
            findings.append(make_finding("EXPOSED_DEBUG_ENDPOINT", "HIGH", url, {
                "path": path,
                "status_code": resp.status_code,
                "content_preview": content[:200],
                "verified": bool(signatures),
            }, confidence))


def _check_sensitive_files(target_url, session, findings):
    for path in SENSITIVE_FILES:
        url = urljoin(target_url, path.lstrip("/"))
        resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp or resp.status_code != 200:
            continue
        content = resp.text
        if len(content) < 50:
            continue
        content_lower = content.lower()
        if any(pattern in content_lower for pattern in NOT_FOUND_PATTERNS):
            continue
        content_first100 = content[:100].lower().encode()
        if any(sig in content_first100 for sig in HTML_SIGNATURES):
            continue
        expected_signatures = FILE_SIGNATURES.get(path, [])
        if expected_signatures:
            content_bytes = content.encode('utf-8', errors='ignore')
            has_signature = any(sig in content_bytes for sig in expected_signatures)
        else:
            has_signature = len(content) > 100
        if has_signature:
            confidence = 0.95 if expected_signatures else 0.6
            findings.append(make_finding("EXPOSED_SENSITIVE_FILE", "HIGH", url, {
                "file": path,
                "status_code": resp.status_code,
                "content_length": len(content),
                "content_preview": content[:200],
                "verified": bool(expected_signatures),
            }, confidence))


def _check_verb_tampering(target_url, session, findings):
    for method in ("TRACE", "DELETE", "PUT", "PATCH", "OPTIONS"):
        resp = safe_request(method, target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if resp and resp.status_code not in (405, 404, 403, 501):
            if method == "TRACE":
                findings.append(make_finding("HTTP_VERB_TAMPERING", "MEDIUM", target_url, {
                    "method": method,
                    "status_code": resp.status_code,
                    "message": f"Server accepts {method} method",
                }, 0.8))


class DetectionCheck:
    def __init__(self):
        self.name = "detection"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
