"""Parser for pip-audit JSON output (pip-audit --format json)."""
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class PipAuditParser(BaseParser):
    """Parser for pip-audit vulnerability scanner output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings
        items = data if isinstance(data, list) else []
        for vuln in items:
            severity = vuln.get("severity", "MEDIUM").upper()
            severity = severity if severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "MEDIUM"
            name = vuln.get("name", "unknown")
            finding = {
                "type": "DEPENDENCY_VULNERABILITY",
                "severity": severity,
                "endpoint": f"pypi:{name}",
                "evidence": {
                    "package": vuln.get("name", ""),
                    "version": vuln.get("version", ""),
                    "fix_version": vuln.get("fix_version", ""),
                    "vulnerable_versions": vuln.get("vulnerable_versions", ""),
                    "vulnerability_id": vuln.get("vulnerability_id", ""),
                    "title": name,
                },
                "confidence": 0.95,
                "tool": "pip_audit",
            }
            findings.append(finding)
        return findings
