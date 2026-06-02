"""
WebScanner parser.

WebScanner.scan() returns findings as Python dicts directly.
When run through the tool_runner subprocess path, findings are JSON-encoded.
This parser handles both cases.
"""

import json
import logging

from .base import BaseParser

logger = logging.getLogger(__name__)


class WebScannerParser(BaseParser):
    """
    Parser for WebScanner tool output.

    WebScanner findings are already structured dicts with:
      - type: vulnerability type
      - severity: CRITICAL/HIGH/MEDIUM/LOW/INFO
      - endpoint: affected URL
      - evidence: dict with details
      - confidence: float
    """

    SEVERITY_MAP = {
        "critical": "CRITICAL",
        "high": "HIGH",
        "medium": "MEDIUM",
        "low": "LOW",
        "info": "INFO",
        "informational": "INFO",
    }

    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse WebScanner output.

        Handles:
        1. JSON array of findings (standard subprocess output)
        2. JSON lines (one finding per line)
        3. Already-structured dict output (when called inline)
        """
        findings = []

        if not raw_output or not raw_output.strip():
            return findings

        # Try JSON array first
        try:
            data = json.loads(raw_output)
            if isinstance(data, list):
                for item in data:
                    finding = self._normalize(item)
                    if finding:
                        findings.append(finding)
                return findings
        except json.JSONDecodeError:
            pass

        # Try JSON lines
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                finding = self._normalize(item)
                if finding:
                    findings.append(finding)
            except json.JSONDecodeError:
                continue

        return findings

    def _normalize(self, item: dict) -> dict | None:
        """Normalize a WebScanner finding dict to standard schema."""
        if not isinstance(item, dict):
            return None

        finding_type = item.get("type") or item.get("vuln_type") or "WEB_VULNERABILITY"
        endpoint = item.get("endpoint") or item.get("url") or ""
        raw_severity = str(item.get("severity") or "medium").lower()
        severity = self.SEVERITY_MAP.get(raw_severity, "MEDIUM")
        confidence = float(item.get("confidence", 0.7))
        evidence = item.get("evidence") or {}

        if not endpoint:
            return None

        return {
            "type": finding_type.upper().replace(" ", "_"),
            "severity": severity,
            "endpoint": endpoint,
            "evidence": evidence if isinstance(evidence, dict) else {"raw": str(evidence)},
            "confidence": confidence,
            "tool": "web_scanner",
        }
