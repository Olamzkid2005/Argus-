"""Parser for jwt_tool output — handles both JSON lines and text formats.

jwt_tool outputs JSON lines like:
    {"vulnerability":"alg=none accepted","severity":"high","parameter":"alg"}

And text lines with indicators:
    [+] This token is vulnerable to algorithm confusion!
    [!] Warning: Signature not verified
    [WARNING] Some security issue
    [-] Nothing here (ignored)
"""
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


SEVERITY_MAP = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "info": "INFO",
}


class JwtToolParser(BaseParser):
    """Parser for jwt_tool output — JSON lines first, then text indicators."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []

        if not raw_output or not raw_output.strip():
            return findings

        # First pass: try each line as JSON
        json_findings = self._parse_json_lines(raw_output)
        findings.extend(json_findings)

        # Second pass: text indicators (only if no JSON findings were found,
        # to avoid double-reporting the same line)
        if not json_findings:
            text_findings = self._parse_text_lines(raw_output)
            findings.extend(text_findings)

        return findings

    def _parse_json_lines(self, raw_output: str) -> list[dict]:
        """Parse JSON lines like {"vulnerability":"...","severity":"high","parameter":"..."}."""
        findings = []
        for line in raw_output.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                if not isinstance(obj, dict):
                    continue
                vuln = obj.get("vulnerability", obj.get("finding", ""))
                severity_raw = obj.get("severity", "medium")
                severity = SEVERITY_MAP.get(severity_raw.lower(), "MEDIUM")
                parameter = obj.get("parameter", obj.get("param", ""))
                finding = {
                    "type": "JWT_VULNERABILITY",
                    "severity": severity,
                    "endpoint": parameter,
                    "evidence": {
                        "vulnerability": vuln,
                        "severity": severity_raw,
                        "parameter": parameter,
                        "source": obj,
                    },
                    "confidence": 0.80,
                    "tool": "jwt_tool",
                }
                findings.append(finding)
            except (json.JSONDecodeError, ValueError):
                continue
        return findings

    def _parse_text_lines(self, raw_output: str) -> list[dict]:
        """Parse text indicators: [+], [!], [WARNING]."""
        findings = []
        for line in raw_output.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("[+]"):
                finding = {
                    "type": "JWT_VULNERABILITY",
                    "severity": "HIGH",
                    "endpoint": f"jwt://{hash(stripped) & 0xffffffff:08x}",
                    "evidence": {
                        "finding": stripped,
                    },
                    "confidence": 0.80,
                    "tool": "jwt_tool",
                }
                findings.append(finding)
            elif stripped.startswith("[!]") or stripped.startswith("[WARNING]"):
                finding = {
                    "type": "JWT_VULNERABILITY",
                    "severity": "MEDIUM",
                    "endpoint": f"jwt://{hash(stripped) & 0xffffffff:08x}",
                    "evidence": {
                        "finding": stripped,
                    },
                    "confidence": 0.60,
                    "tool": "jwt_tool",
                }
                findings.append(finding)
        return findings
