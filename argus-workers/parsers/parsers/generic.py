"""
Generic parser — fallback for tools without a dedicated parser.

Uses heuristic extraction (JSON detection, URL/IP/CVE regex)
to produce findings from any tool output, ensuring no tool
result is silently dropped.
"""

import json
import logging
import re

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"https?://[^\s\"'>)]+")
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_ERROR_PATTERN = re.compile(
    r"(error|fail|critical|vulnerability|warning)\s*:?\s*(.*)", re.IGNORECASE
)

_SEVERITY_MAP = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "info": "INFO",
    "none": "INFO",
}

_CONFIDENCE_MAP = {
    "high": 0.90,
    "medium": 0.50,
    "low": 0.20,
}


def _normalize_severity(severity: str) -> str:
    """Map a severity string to a standard level."""
    return _SEVERITY_MAP.get(severity.strip().lower(), "MEDIUM")


def _normalize_confidence(confidence: str) -> float:
    """Map a confidence string to a float."""
    return _CONFIDENCE_MAP.get(confidence.strip().lower(), 0.50)


class GenericParser(BaseParser):
    """Fallback parser that uses heuristic extraction on any tool output."""

    def parse(self, raw_output: str) -> list[dict]:
        if not raw_output or not raw_output.strip():
            return []

        # Try JSON first
        json_findings = _try_json(raw_output)
        if json_findings:
            return json_findings

        # Fall back to regex extraction
        return _regex_extract(raw_output)


def _try_json(output: str) -> list[dict] | None:
    """Attempt to parse output as JSON and extract findings."""
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None

    items = data if isinstance(data, list) else [data]
    findings = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = (
            item.get("title")
            or item.get("name")
            or item.get("message")
            or item.get("finding")
            or "Generic finding"
        )
        severity_raw = str(item.get("severity", "medium"))
        confidence_raw = str(item.get("confidence", "medium"))

        findings.append(
            {
                "type": "GENERIC_FINDING",
                "severity": _normalize_severity(severity_raw),
                "endpoint": str(item.get("url", item.get("endpoint", ""))),
                "title": str(title),
                "evidence": item,
                "confidence": _normalize_confidence(confidence_raw),
                "tool": item.get("tool", "unknown"),
            }
        )
    return findings


def _regex_extract(output: str) -> list[dict]:
    """Extract findings using regex patterns (URLs, IPs, CVEs, errors)."""
    findings = []

    urls = _URL_PATTERN.findall(output)
    ips = _IP_PATTERN.findall(output)
    cves = _CVE_PATTERN.findall(output)

    # Capture CVEs as findings
    for cve in set(cves):
        findings.append(
            {
                "type": "CVE_REFERENCE",
                "severity": "HIGH",
                "endpoint": "",
                "evidence": {"type": "cve", "content": cve},
                "confidence": 0.30,
                "tool": "unknown",
                "title": f"CVE referenced: {cve}",
            }
        )

    # Capture error patterns if no more specific findings found
    error_matches = _ERROR_PATTERN.findall(output)
    if error_matches and not (cves or urls or ips):
        for severity_tag, msg in error_matches[:5]:
            findings.append(
                {
                    "type": "GENERIC_FINDING",
                    "severity": _normalize_severity(severity_tag),
                    "endpoint": "",
                    "evidence": {"type": "text", "content": msg.strip()},
                    "confidence": 0.30,
                    "tool": "unknown",
                    "title": msg.strip()[:120] or f"Pattern: {severity_tag}",
                }
            )

    # Last resort: capture raw output as a single finding
    if not findings and output.strip():
        findings.append(
            {
                "type": "RAW_OUTPUT",
                "severity": "INFO",
                "endpoint": "",
                "evidence": {"type": "raw", "content": output[:2000]},
                "confidence": 0.10,
                "tool": "unknown",
                "title": "Raw output captured",
            }
        )

    return findings
