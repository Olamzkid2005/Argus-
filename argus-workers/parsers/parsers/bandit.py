"""Parser for bandit JSON output (bandit -f json)."""
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class BanditParser(BaseParser):
    """Parser for bandit SAST output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings
        results = data.get("results", [])
        for issue in results:
            severity = issue.get("issue_severity", "LOW").upper()
            severity = severity if severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO") else "LOW"
            finding = {
                "type": f"BANDIT_{issue.get('test_id', 'UNKNOWN')}",
                "severity": severity,
                "endpoint": f"file:{issue.get('filename', '')}:{issue.get('line_number', 0)}",
                "evidence": {
                    "file": issue.get("filename", ""),
                    "line": issue.get("line_number", 0),
                    "code": issue.get("code", ""),
                    "issue_text": issue.get("issue_text", ""),
                    "test_name": issue.get("test_name", ""),
                },
                "confidence": 0.90,
                "tool": "bandit",
            }
            findings.append(finding)
        return findings
