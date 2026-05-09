"""
Scan JavaScript files for exposed secrets and credentials.
"""
import logging
import re

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

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


def run_check(target_url: str, session, findings: list) -> list[dict]:
    return JsSecretsCheck().check(target_url, session, findings)
def _scan_content_for_secrets(content: str, source: str, findings: list):
    for pattern, secret_type in JS_SECRET_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            masked = []
            for m in matches[:3]:
                if len(m) > 8:
                    masked.append(m[:4] + "..." + m[-4:])
                else:
                    masked.append("***")
            findings.append(make_finding("EXPOSED_SECRET", "CRITICAL", source, {
                "secret_type": secret_type,
                "matches_found": len(matches),
                "masked_values": masked,
            }, 0.85))


class JsSecretsCheck:
    def __init__(self):
        self.name = "js_secrets"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
