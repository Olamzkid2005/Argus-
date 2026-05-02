"""
Parser for Semgrep JSON output.

Semgrep output format:
    {
      "results": [
        {
          "check_id": "python.lang.security.audit",
          "path": "/path/to/file.py",
          "start": {"line": 10, "col": 5},
          "end": {"line": 10, "col": 80},
          "extra": {
            "message": "Found security issue",
            "severity": "WARNING",
            "metadata": {
              "cwe": "CWE-78",
              "owasp": "A01:2021"
            },
            "lines": "dangerous_code()"
          }
        }
      ]
    }
"""
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)

SEVERITY_MAP = {
    "ERROR": "HIGH",
    "WARNING": "MEDIUM",
    "INFO": "LOW",
    "CRITICAL": "CRITICAL",
}


class SemgrepParser(BaseParser):
    """Parser for semgrep JSON output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings

        results = data.get("results", []) if isinstance(data, dict) else []
        for r in results:
            path = r.get("path", "")
            check_id = r.get("check_id", "UNKNOWN")
            start = r.get("start", {}) or {}
            line = start.get("line", 0)
            extra = r.get("extra", {}) or {}
            message = extra.get("message", "")
            severity = extra.get("severity", "WARNING")
            metadata = extra.get("metadata", {}) or {}
            cwe = metadata.get("cwe", "")
            owasp = metadata.get("owasp", "")
            lines = extra.get("lines", "")

            finding = {
                "type": f"CODE_VULNERABILITY",
                "severity": SEVERITY_MAP.get(severity, "MEDIUM"),
                "endpoint": f"file:{path}:{line}",
                "evidence": {
                    "file": path,
                    "line": line,
                    "check_id": check_id,
                    "message": message,
                    "code_snippet": lines[:500] if lines else "",
                    "cwe": cwe,
                    "owasp": owasp,
                },
                "confidence": 0.85,
                "tool": "semgrep",
            }
            findings.append(finding)

        return findings
