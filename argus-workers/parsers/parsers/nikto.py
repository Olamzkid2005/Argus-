"""
Parser for Nikto output. Handles JSON, CSV and plain-text formats.

Nikto is invoked without -Format so it prints its findings to stdout (with
-Format it writes a nikto_<host>_<timestamp>.<ext> file in the current
directory instead, which the worker never reads). The parser therefore tries
JSON first, then CSV, then the plain-text report.
"""

import csv
import io
import json
import logging
import re

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Nikto tags real findings with an OSVDB/plugin id: "+ [013587] /: <detail>".
_NIKTO_FINDING_PATTERN = re.compile(r"^\+\s+\[(\d+)\]\s+(.*)$", re.MULTILINE)


def _text_severity(msg: str) -> str:
    lowered = msg.lower()
    if re.search(r"\bcritical\b", lowered):
        return "CRITICAL"
    if re.search(r"\bhigh\b", lowered):
        return "HIGH"
    if re.search(r"\b(?:info|note)\b", lowered):
        return "INFO"
    return "MEDIUM"


#: See the note in tool_core/parser/parsers/nikto.py: nikto's text report is
#: comma-heavy prose, and reading it as CSV manufactured findings out of a
#: method list. CSV is only attempted when the output looks like CSV.
def _looks_like_csv(raw_output: str) -> bool:
    lines = [line for line in raw_output.splitlines() if line.strip()][:6]
    if not lines:
        return False
    if any(line.lstrip().startswith(("+", "-")) for line in lines):
        return False
    if "Nikto" in raw_output or "Target IP" in raw_output:
        return False
    return any(line.count(",") >= 5 for line in lines)


_SEE_URL = re.compile(r"\s*See:\s*https?://\S+", re.IGNORECASE)
_LOCATION_PREFIX = re.compile(
    r"^(?:/|/[\w.\-][\w.\-?=&%]*(?:/[\w.\-?=&%]*)*|OPTIONS|GET|POST|HEAD|TRACE|PUT|DELETE)\s*:\s+"
)


def _headline(content: str) -> str:
    text = _SEE_URL.sub("", content).strip()
    text = _LOCATION_PREFIX.sub("", text) or text
    text = text.rstrip(" .")
    return (text or content.strip())[:120]


class NiktoParser(BaseParser):
    """Parser for nikto output — tries JSON, then CSV, then text."""

    def parse(self, raw_output: str) -> list[dict]:
        # Try JSON first
        try:
            items = json.loads(raw_output)
            if isinstance(items, list):
                return self._parse_json(items)
        except (json.JSONDecodeError, ValueError):
            pass
        # Fall back to CSV, but only for output that is CSV
        if _looks_like_csv(raw_output):
            findings = self._parse_csv(raw_output)
            if findings:
                return findings
        # Finally the plain-text report nikto prints when no -Format is given
        return self._parse_text(raw_output)

    def _parse_text(self, raw_output: str) -> list[dict]:
        findings = []
        for osvdb, content in _NIKTO_FINDING_PATTERN.findall(raw_output):
            content = content.strip()
            if not content:
                continue
            findings.append(
                {
                    "type": "WEB_SERVER_VULNERABILITY",
                    "title": _headline(content),
                    "severity": _text_severity(content),
                    "endpoint": "",
                    "evidence": {
                        "message": content,
                        "osvdb": osvdb,
                    },
                    "confidence": 0.70,
                    "tool": "nikto",
                }
            )
        return findings

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
            findings.append(
                {
                    "type": "WEB_SERVER_VULNERABILITY",
                    "title": _headline(msg) if msg.strip() else f"nikto {osvdb}".strip(),
                    "severity": severity,
                    "endpoint": url,
                    "evidence": {
                        "message": msg,
                        "osvdb": osvdb,
                        "nikto_item": item,
                    },
                    "confidence": 0.70,
                    "tool": "nikto",
                }
            )
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
            findings.append(
                {
                    "type": "WEB_SERVER_VULNERABILITY",
                    "title": _headline(description) if description else f"{method} {url}".strip(),
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
                }
            )
        return findings
