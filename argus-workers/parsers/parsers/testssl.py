"""Parser for testssl.sh output — handles JSON array and NDJSON (one JSON object per line).

testssl.sh --jsonfile outputs one JSON object per line (NDJSON):
    {"host":"example.com","port":443,"severity":"HIGH","id":"SSL_TEST","finding":"..."}

testssl.sh --json outputs a JSON array:
    [{"host":"example.com","port":443,"severity":"HIGH","id":"SSL_TEST","finding":"..."}]
"""
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)

SEVERITY_MAP = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFO": "INFO",
    "OK": "INFO",
    "WARN": "MEDIUM",
}


class TestsslParser(BaseParser):
    """Parser for testssl.sh output — tries JSON array first, then NDJSON."""

    def parse(self, raw_output: str) -> list[dict]:
        if not raw_output or not raw_output.strip():
            return []

        # Try parsing as a JSON array
        try:
            items = json.loads(raw_output)
            if isinstance(items, list):
                return self._parse_findings(items)
        except (json.JSONDecodeError, ValueError):
            pass

        # Fall back: parse as NDJSON (one JSON object per line)
        findings = []
        for line in raw_output.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    finding = self._make_finding(obj)
                    if finding:
                        findings.append(finding)
            except json.JSONDecodeError:
                continue
        return findings

    def _parse_findings(self, items: list) -> list[dict]:
        """Parse a JSON array of finding objects."""
        findings = []
        for obj in items:
            if not isinstance(obj, dict):
                continue
            finding = self._make_finding(obj)
            if finding:
                findings.append(finding)
        return findings

    def _make_finding(self, data: dict) -> dict | None:
        """Convert a single testssl finding dict into the standard format."""
        severity_raw = (data.get("severity") or "INFO").upper()
        severity = SEVERITY_MAP.get(severity_raw, "INFO")
        host = data.get("host", data.get("ip", ""))
        port = data.get("port", "")
        endpoint = f"{host}:{port}" if port else host

        return {
            "type": "TLS_VULNERABILITY",
            "severity": severity,
            "endpoint": endpoint,
            "evidence": {
                "id": data.get("id", ""),
                "finding": data.get("finding", ""),
                "severity": severity_raw,
            },
            "confidence": 0.90,
            "tool": "testssl",
        }
