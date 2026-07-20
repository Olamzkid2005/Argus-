"""Parser for npm audit JSON output (npm audit --json)."""

import json
import logging
from typing import Any

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class NpmAuditParser(BaseParser):
    """Parser for npm audit vulnerability scanner output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings: list[dict[str, Any]] = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings

        vulnerabilities = (
            data.get("vulnerabilities", {}) if isinstance(data, dict) else {}
        )
        for pkg_name, vuln_info in vulnerabilities.items():
            severity = vuln_info.get("severity", "medium").upper()
            severity = (
                severity
                if severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
                else "MEDIUM"
            )
            via = vuln_info.get("via", [])
            finding = {
                "type": "DEPENDENCY_VULNERABILITY",
                "severity": severity,
                "endpoint": f"npm:{pkg_name}",
                "evidence": {
                    "package": pkg_name,
                    "version": vuln_info.get("version", "unknown"),
                    "severity": vuln_info.get("severity", "medium"),
                    "via": via,
                    "fix_available": vuln_info.get("fixAvailable", False),
                    "title": f"Vulnerability in {pkg_name}",
                },
                "confidence": 0.95,
                "tool": "npm_audit",
            }
            findings.append(finding)

        return findings
