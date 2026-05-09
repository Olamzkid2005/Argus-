"""Parser for gitleaks JSON output (gitleaks detect --json)."""
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
                "endpoint": item.get("File", ""),
                "evidence": {
                    "description": item.get("Description", ""),
                    "file": item.get("File"),
                    "line": item.get("StartLine"),
                    "commit": item.get("Commit"),
                    "author": item.get("Author"),
                    "email": item.get("Email"),
                    "repository": item.get("Repo"),
                    "offender": (item.get("Secret") or "")[:100],
                    "match": item.get("Match"),
                },
                "tool": "gitleaks",
            }
            findings.append(finding)
        return findings
