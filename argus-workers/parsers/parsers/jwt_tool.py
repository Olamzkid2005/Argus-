"""Parser for jwt_tool output — handles both JSON lines and text formats.

jwt_tool outputs JSON lines like:
    {"vulnerability":"alg=none accepted","severity":"high","parameter":"alg"}

And text lines with indicators:
    [+] This token is vulnerable to algorithm confusion!
    [!] Warning: Signature not verified
    [WARNING] Some security issue
    [-] Nothing here (ignored)
"""

import hashlib
import json
import logging
from typing import Any

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
        findings: list[dict[str, Any]] = []

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
        for line in raw_output.splitlines():
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

    # Informational keywords that should NOT be treated as findings.
    # jwt_tool outputs many [+]/[!] lines that are status updates, not vulnerabilities.
    _INFO_KEYWORDS = {
        "loaded", "decoded", "identified", "using file",
        "processed", "parsed", "reading", "checking",
        "attempting", "trying", "running",
    }
    # Confirmed vulnerability keywords — only these trigger a finding.
    _VULN_KEYWORDS = {
        "vulnerable", "vulnerability", "CVE",
        "weak", "weakness", "bypass", "bypassed",
        "misconfiguration", "exploit", "exploitable",
        "unrestricted", "insecure",
        # jwt_tool-specific vulnerability indicators
        "cracked",
        "forged", "forgery",
        "traversal",
        "none algorithm", "none' algorithm",
        "accepts none", "empty signature", "no signature",
        "alg:none",
    }

    def _parse_text_lines(self, raw_output: str) -> list[dict]:
        """Parse text indicators: [+], [!], [WARNING].

        Only lines containing confirmed vulnerability keywords are treated as
        findings. Lines with informational keywords ("loaded", "decoded", etc.)
        are skipped to prevent false positives.
        """
        findings = []
        for line in raw_output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("[+]"):
                line_lower = stripped.lower()
                # Skip informational lines — they're not vulnerabilities
                if any(kw in line_lower for kw in self._INFO_KEYWORDS):
                    continue
                # Only emit a finding if a confirmed vulnerability keyword is present
                if not any(kw in line_lower for kw in self._VULN_KEYWORDS):
                    continue
                finding = {
                    "type": "JWT_VULNERABILITY",
                    "severity": "HIGH",
                    "endpoint": f"jwt://{hashlib.sha256(stripped.encode()).hexdigest()[:8]}",
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
                    "endpoint": f"jwt://{hashlib.sha256(stripped.encode()).hexdigest()[:8]}",
                    "evidence": {
                        "finding": stripped,
                    },
                    "confidence": 0.60,
                    "tool": "jwt_tool",
                }
                findings.append(finding)
        return findings
