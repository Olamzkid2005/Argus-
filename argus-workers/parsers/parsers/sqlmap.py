"""
Parser for sqlmap output — handles both JSON and text output formats.

SQLMap JSON output (from --json or log files) has findings in a data array:
    {
        "data": [
            {
                "url": "http://example.com/page?id=1",
                "parameters": {
                    "id": {
                        "type": "GET",
                        "title": "Place-based boolean blind injection",
                        "payload": "1 AND 1=1"
                    }
                }
            }
        ]
    }

SQLMap text output contains the phrase:
    "sqlmap identified the following injection point"
"""
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class SqlmapParser(BaseParser):
    """Parser for sqlmap output — tries JSON first, then text pattern matching."""

    def parse(self, raw_output: str) -> list[dict]:
        if not raw_output or not raw_output.strip():
            return []

        # Try JSON first
        findings = self._parse_json(raw_output)
        if findings:
            return findings

        # Fall back to text pattern matching
        return self._parse_text(raw_output)

    def _parse_json(self, raw_output: str) -> list[dict]:
        """Parse JSON output — handles both the data-array format and flat formats."""
        try:
            data = json.loads(raw_output)
        except (json.JSONDecodeError, ValueError):
            return []

        findings = []

        # Format 1: {"data": [...]}
        entries = data if isinstance(data, list) else data.get("data", data.get("entries", []))
        if not isinstance(entries, list):
            entries = [entries]

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url", "")
            parameters = entry.get("parameters", entry.get("parameter", {}))
            if isinstance(parameters, dict):
                for param_name, param_info in parameters.items():
                    if not isinstance(param_info, dict):
                        continue
                    title = param_info.get("title", "")
                    payload = param_info.get("payload", "")
                    vuln_type = param_info.get("type", "")
                    technique = (
                        "BOOLEAN_BLIND" if "boolean" in title.lower()
                        else "TIME_BLIND" if "time" in title.lower()
                        else "UNION" if "union" in title.lower()
                        else "ERROR" if "error" in title.lower()
                        else "STACKED" if "stacked" in title.lower()
                        else "SQL_INJECTION"
                    )
                    finding = {
                        "type": technique,
                        "severity": "CRITICAL",
                        "endpoint": f"{url}#{param_name}" if param_name else url,
                        "evidence": {
                            "url": url,
                            "parameter": param_name,
                            "title": title,
                            "payload": payload,
                            "vuln_type": vuln_type,
                            "raw": param_info,
                        },
                        "confidence": 0.95,
                        "tool": "sqlmap",
                    }
                    findings.append(finding)
            elif isinstance(parameters, str):
                # Flat format: parameters is a string like "id"
                finding = {
                    "type": "SQL_INJECTION",
                    "severity": "CRITICAL",
                    "endpoint": f"{url}#{parameters}" if parameters else url,
                    "evidence": {
                        "url": url,
                        "parameter": parameters,
                        "raw": entry,
                    },
                    "confidence": 0.90,
                    "tool": "sqlmap",
                }
                findings.append(finding)

        return findings

    def _parse_text(self, raw_output: str) -> list[dict]:
        """Parse text output looking for SQL injection indicators."""
        findings = []

        if "sqlmap identified the following injection point" in raw_output.lower():
            finding = {
                "type": "SQL_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "",
                "evidence": {
                    "raw_output": raw_output[:1000],
                },
                "confidence": 0.9,
                "tool": "sqlmap",
            }
            findings.append(finding)

        return findings
