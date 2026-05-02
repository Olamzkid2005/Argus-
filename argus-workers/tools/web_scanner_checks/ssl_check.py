"""
SSL/TLS certificate and configuration verification.
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


def run_check(target_url: str, session, findings: list) -> list[dict]:
    parsed = urlparse(target_url)
    hostname = parsed.hostname
    port = parsed.port or 443

    if not hostname:
        return findings

    if parsed.scheme != "https":
        findings.append(make_finding("NO_HTTPS", "HIGH", target_url, {
            "scheme": parsed.scheme,
            "message": "Target does not use HTTPS",
        }, 0.95))
        return findings

    context = ssl.create_default_context()
    sock = None
    ssock = None

    try:
        sock = socket.create_connection((hostname, port), timeout=_DEFAULT_TIMEOUT)
        ssock = context.wrap_socket(sock, server_hostname=hostname)

        try:
            cert = ssock.getpeercert()
        except (ValueError, ssl.SSLError):
            cert = None
        cipher = ssock.cipher()
        version = ssock.version()

        if cert:
            not_after = cert.get("notAfter")
            if not_after:
                expiry = ssl.cert_time_to_seconds(not_after)
                if expiry < time.time():
                    findings.append(make_finding("EXPIRED_SSL_CERTIFICATE", "HIGH", f"{hostname}:{port}", {
                        "expiry_date": not_after,
                        "subject": cert.get("subject"),
                    }, 0.95))
            issuer = cert.get("issuer")
            subject = cert.get("subject")
            if issuer == subject:
                findings.append(make_finding("SELF_SIGNED_CERTIFICATE", "MEDIUM", f"{hostname}:{port}", {
                    "issuer": issuer,
                    "subject": subject,
                }, 0.9))

        weak_versions = ["SSLv3", "TLSv1", "TLSv1.1"]
        if version in weak_versions:
            findings.append(make_finding("WEAK_TLS_VERSION", "HIGH", f"{hostname}:{port}", {
                "tls_version": version,
                "message": f"{version} is deprecated and insecure",
            }, 0.95))

        if cipher:
            cipher_name = cipher[0]
            if any(wc in cipher_name for wc in WEAK_CIPHERS):
                findings.append(make_finding("WEAK_SSL_CIPHER", "HIGH", f"{hostname}:{port}", {
                    "cipher": cipher_name,
                    "message": f"Weak cipher detected: {cipher_name}",
                }, 0.85))

    except ssl.SSLError as e:
        findings.append(make_finding("SSL_ERROR", "MEDIUM", target_url, {
            "error": str(e),
            "message": "SSL/TLS handshake failed",
        }, 0.8))
    except OSError:
        logger.debug(f"SSL verification socket error for {hostname}:{port}")
    except Exception as e:
        logger.debug(f"SSL verification error: {e}")
    finally:
        if ssock:
            with contextlib.suppress(Exception):
                ssock.close()
        if sock:
            with contextlib.suppress(Exception):
                sock.close()

    return findings


class UsslCheck:
    def __init__(self):
        self.name = "ssl"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
