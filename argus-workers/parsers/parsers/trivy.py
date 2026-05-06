"""Parser for trivy filesystem scan JSON output (trivy fs --format json)."""
import json
import logging
from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class TrivyParser(BaseParser):
    """Parser for trivy vulnerability scanner output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings
        for result in data.get("Results", []):
            target = result.get("Target", "")
            for vuln in result.get("Vulnerabilities", []):
                severity = vuln.get("Severity", "UNKNOWN").upper()
                if severity not in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNKNOWN"):
                    severity = "MEDIUM"
                finding = {
                    "type": "DEPENDENCY_VULNERABILITY",
                    "severity": severity,
                    "endpoint": f"{target}:{vuln.get('PkgName', '')}",
                    "evidence": {
                        "package": vuln.get("PkgName"),
                        "installed_version": vuln.get("InstalledVersion"),
                        "fixed_version": vuln.get("FixedVersion"),
                        "vulnerability_id": vuln.get("VulnerabilityID"),
                        "title": vuln.get("Title", ""),
                        "target": target,
                    },
                    "tool": "trivy",
                }
                findings.append(finding)
        return findings
