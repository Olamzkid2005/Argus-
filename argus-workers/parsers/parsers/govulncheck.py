"""Parser for govulncheck JSON output (govulncheck ./... -json)."""
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class GovulncheckParser(BaseParser):
    """Parser for govulncheck Go vulnerability scanner output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            for line in raw_output.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    vuln = json.loads(line)
                except json.JSONDecodeError:
                    continue

                severity = "HIGH" if vuln.get("severity") == "HIGH" else "MEDIUM"
                vuln_info = vuln.get("vulnerability") or {}
                finding = {
                    "type": "DEPENDENCY_VULNERABILITY",
                    "severity": severity,
                    "endpoint": f"go:{vuln.get('module', '')}",
                    "evidence": {
                        "module": vuln.get("module", ""),
                        "version": vuln.get("version", ""),
                        "fixed_version": vuln.get("fixed_version", ""),
                        "vulnerability": vuln_info,
                        "title": vuln_info.get("title", "Go Vulnerability"),
                    },
                    "confidence": 0.95,
                    "tool": "govulncheck",
                }
                findings.append(finding)
        except Exception as e:
            logger.warning("govulncheck parse error: %s", e)

        return findings
