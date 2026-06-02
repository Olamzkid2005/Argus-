"""Parser for gitleaks JSON output (gitleaks detect --json)."""
import hashlib
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class GitleaksParser(BaseParser):
    """Parser for gitleaks secret scan output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not item or not isinstance(item, dict):
                continue
            finding = {
                "type": "SECRET_LEAK",
                "severity": (item.get("Severity") or "high").upper(),
                "endpoint": item.get("File") or item.get("Commit") or f"gitleaks:{item.get('RuleID', 'unknown')}",
                "evidence": {
                    "description": item.get("Description", ""),
                    "file": item.get("File"),
                    "line": item.get("StartLine"),
                    "commit": item.get("Commit"),
                    "author": item.get("Author"),
                    "email": item.get("Email"),
                    "repository": item.get("Repo"),
                    # Hash the secret instead of storing plaintext (fix 6.6)
                    # SHA-256 hash allows dedup without leaking secrets
                    "offender_hash": hashlib.sha256((item.get("Secret") or "").encode()).hexdigest()[:16] if item.get("Secret") else "",
                    "has_secret": bool(item.get("Secret")),
                    "match": item.get("Match"),
                },
                "tool": "gitleaks",
            }
            findings.append(finding)
        return findings
