"""
SSL/TLS certificate and configuration verification with HSTS preload checks.
"""
import contextlib
import logging
import ssl
import socket
import time
from urllib.parse import urlparse

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

WEAK_CIPHERS = ["RC4", "DES", "3DES", "MD5", "NULL", "EXPORT", "anon", "CBC"]
WEAK_TLS_VERSIONS = ["SSLv3", "TLSv1", "TLSv1.1"]
HSTS_MIN_MAX_AGE = 31536000


def run_check(target_url: str, session, findings: list) -> list[dict]:
    return SslCheck().check(target_url, session, findings)
def _check_hsts(target_url: str, hostname: str, session, findings: list):
    try:
        resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if resp is None:
            logger.debug(f"HSTS check: no response for {target_url}")
            return
    except Exception:
        logger.debug(f"HSTS check request failed for {target_url}")
        return

    hsts = resp.headers.get("Strict-Transport-Security", "")
    if not hsts:
        findings.append(make_finding(
            "MISSING_HSTS", "MEDIUM", target_url, {
                "message": "No Strict-Transport-Security header found",
                "header": None,
            }, 0.95,
        ))
        return

    directives = {}
    for part in hsts.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, val = part.split("=", 1)
            directives[key.strip().lower()] = val.strip()
        else:
            directives[part.strip().lower()] = True

    if "max-age" not in directives:
        findings.append(make_finding(
            "HSTS_MISSING_MAX_AGE", "HIGH", target_url, {
                "message": "HSTS header present but missing max-age directive",
                "raw_header": hsts,
            }, 0.95,
        ))
        return

    try:
        max_age = int(directives["max-age"])
    except (ValueError, TypeError):
        findings.append(make_finding(
            "HSTS_INVALID_MAX_AGE", "HIGH", target_url, {
                "message": "HSTS max-age is not a valid integer",
                "max_age_raw": directives["max-age"],
                "raw_header": hsts,
            }, 0.95,
        ))
        return

    if max_age < HSTS_MIN_MAX_AGE:
        findings.append(make_finding(
            "HSTS_LOW_MAX_AGE", "MEDIUM", target_url, {
                "message": f"HSTS max-age ({max_age}s) is below preload minimum ({HSTS_MIN_MAX_AGE}s)",
                "max_age": max_age,
                "required_max_age": HSTS_MIN_MAX_AGE,
                "raw_header": hsts,
            }, 0.9,
        ))

    if "includesubdomains" not in directives:
        findings.append(make_finding(
            "HSTS_MISSING_INCLUDE_SUBDOMAINS", "HIGH", target_url, {
                "message": "HSTS header missing includeSubDomains directive — subdomains not protected",
                "raw_header": hsts,
            }, 0.95,
        ))

    if "preload" not in directives:
        findings.append(make_finding(
            "HSTS_MISSING_PRELOAD", "LOW", target_url, {
                "message": "HSTS header missing preload directive — cannot submit to browser preload lists",
                "raw_header": hsts,
            }, 0.85,
        ))


def _check_cert_expiry(cert: dict, hostname: str, port: int, findings: list):
    not_after = cert.get("notAfter")
    if not not_after:
        return
    try:
        expiry = ssl.cert_time_to_seconds(not_after)
    except Exception:
        logger.debug(f"Could not parse notAfter date for {hostname}:{port}: {not_after}")
        return

    now = time.time()
    if expiry < now:
        findings.append(make_finding(
            "EXPIRED_SSL_CERTIFICATE", "HIGH", f"{hostname}:{port}", {
                "expiry_date": not_after,
                "subject": cert.get("subject"),
            }, 0.95,
        ))
    elif expiry - now < 30 * 86400:
        findings.append(make_finding(
            "SSL_CERT_EXPIRING_SOON", "MEDIUM", f"{hostname}:{port}", {
                "expiry_date": not_after,
                "days_remaining": int((expiry - now) / 86400),
                "message": f"Certificate expires within 30 days ({not_after})",
            }, 0.9,
        ))


def _check_self_signed(cert: dict, hostname: str, port: int, findings: list):
    issuer = cert.get("issuer")
    subject = cert.get("subject")
    if issuer is not None and subject is not None and issuer == subject:
        findings.append(make_finding(
            "SELF_SIGNED_CERTIFICATE", "MEDIUM", f"{hostname}:{port}", {
                "issuer": issuer,
                "subject": subject,
            }, 0.9,
        ))


def _check_san(cert: dict, hostname: str, port: int, findings: list):
    sans = cert.get("subjectAltName")
    if sans is None or len(sans) == 0:
        findings.append(make_finding(
            "MISSING_SAN", "MEDIUM", f"{hostname}:{port}", {
                "message": "Certificate has no Subject Alternative Names (SANs)",
                "subject": cert.get("subject"),
            }, 0.85,
        ))


def _check_tls_version(version: str | None, hostname: str, port: int, findings: list):
    if version and version in WEAK_TLS_VERSIONS:
        findings.append(make_finding(
            "WEAK_TLS_VERSION", "HIGH", f"{hostname}:{port}", {
                "tls_version": version,
                "message": f"{version} is deprecated and insecure",
            }, 0.95,
        ))


def _check_weak_cipher(cipher, findings: list, hostname: str, port: int):
    if cipher:
        cipher_name = cipher[0]
        if any(wc in cipher_name for wc in WEAK_CIPHERS):
            findings.append(make_finding(
                "WEAK_SSL_CIPHER", "HIGH", f"{hostname}:{port}", {
                    "cipher": cipher_name,
                    "message": f"Weak cipher detected: {cipher_name}",
                }, 0.85,
            ))


class SslCheck:
    def __init__(self):
        self.name = "ssl"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
