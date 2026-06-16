"""
Parser for Nikto output. Handles both JSON and CSV formats.

Nikto is invoked with -Format csv during recon, but the parser
tries JSON first (for future compatibility) then falls back to CSV.
"""
import csv
import io
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class NiktoParser(BaseParser):
    """Parser for nikto output — tries JSON then CSV."""

    def parse(self, raw_output: str) -> list[dict]:
        # Try JSON first
        try:
            items = json.loads(raw_output)
            if isinstance(items, list):
                return self._parse_json(items)
        except (json.JSONDecodeError, ValueError):
            pass
        # Fall back to CSV
        return self._parse_csv(raw_output)

    def _parse_json(self, items: list) -> list[dict]:
        findings = []
        for item in items:
            msg = item.get("msg", "")
            osvdb = item.get("OSVDB", "")
            url = item.get("url", "")
            severity = "MEDIUM"
            if any(kw in msg.lower() for kw in ["critical", "high"]):
                severity = "HIGH"
            elif any(kw in msg.lower() for kw in ["info", "note"]):
                severity = "INFO"
            findings.append({
                "type": "WEB_SERVER_VULNERABILITY",
                "severity": severity,
                "endpoint": url,
                "evidence": {
                    "message": msg,
                    "osvdb": osvdb,
                    "nikto_item": item,
                },
                "confidence": 0.70,
                "tool": "nikto",
            })
        return findings

    def _parse_csv(self, raw_output: str) -> list[dict]:
        """
        Parse nikto CSV output.
        CSV format (Nikto 2.x): hostname,port,osvdb,method,url,description
        """
        findings = []
        reader = csv.reader(io.StringIO(raw_output))
        for row in reader:
            if not row or len(row) < 5:
                continue
            hostname = row[0].strip() if len(row) > 0 else ""
            port = row[1].strip() if len(row) > 1 else ""
            osvdb = row[2].strip() if len(row) > 2 else ""
            method = row[3].strip() if len(row) > 3 else ""
            url = row[4].strip() if len(row) > 4 else ""
            description = row[5].strip() if len(row) > 5 else ""
            endpoint = f"{hostname}:{port}" if port else hostname
            findings.append({
                "type": "WEB_SERVER_VULNERABILITY",
                "severity": "MEDIUM",
                "endpoint": endpoint,
                "evidence": {
                    "hostname": hostname,
                    "port": port,
                    "osvdb": osvdb,
                    "method": method,
                    "url": url,
                    "description": description,
                },
                "confidence": 0.65,
                "tool": "nikto",
            })
        return findings
