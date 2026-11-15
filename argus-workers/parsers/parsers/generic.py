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


#: Parser-produced findings may carry a number instead of a name. The worker's
#: own verifiers (playwright-bola/xss/privesc) emit `"severity": 4` for a
#: confirmed issue and `0` for a clean result on the 0-4 INFO..CRITICAL scale.
#: Read as a string, both fell through to the MEDIUM default: every confirmed
#: finding was reported as MEDIUM *and* every "No X detected" sentinel became a
#: MEDIUM finding of its own.
_NUMERIC_SEVERITY = {
    0: "INFO",
    1: "LOW",
    2: "MEDIUM",
    3: "HIGH",
    4: "CRITICAL",
    5: "CRITICAL",
}

#: A verifier that found nothing still prints a title; that title is a result,
#: not a finding.
_NEGATIVE_RESULT = re.compile(
    r"^no\b.*\b(detected|found|identified|discovered)\b", re.IGNORECASE
)


def _normalize_severity(severity) -> str:
    """Map a severity name or the 0-4 scale onto a standard level."""
    if isinstance(severity, bool):
        return "MEDIUM"
    if isinstance(severity, (int, float)) and float(severity).is_integer():
        return _NUMERIC_SEVERITY.get(int(severity), "MEDIUM")
    text = str(severity).strip().lower()
    if text.isdigit():
        return _NUMERIC_SEVERITY.get(int(text), "MEDIUM")
    return _SEVERITY_MAP.get(text, "MEDIUM")


def _normalize_confidence(confidence) -> float:
    """Map a confidence name or the verifier's 0-5 scale to a float."""
    if isinstance(confidence, bool):
        return 0.50
    if isinstance(confidence, (int, float)):
        level = float(confidence)
        if level > 1:  # 0-5 scale
            level = level / 5
        return max(0.0, min(1.0, level))
    text = str(confidence).strip().lower()
    if text.replace(".", "", 1).isdigit():
        return _normalize_confidence(float(text))
    return _CONFIDENCE_MAP.get(text, 0.50)


class GenericParser(BaseParser):
    """Fallback parser that uses heuristic extraction on any tool output."""

    def parse(self, raw_output: str) -> list[dict]:
        if not raw_output or not raw_output.strip():
            return []

        # Try JSON first; JSON is authoritative, so an empty result means the
        # tool found nothing rather than falling through to the regex
        # heuristics (which would mine the envelope's own "error": "" key).
        json_findings = _try_json(raw_output)
        if json_findings is not None:
            return json_findings

        # Fall back to regex extraction
        return _regex_extract(raw_output)


def _try_json(output: str) -> list[dict] | None:
    """Attempt to parse output as JSON and extract findings."""
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None

    # Tool launchers (tools/run_agent_tool.py) print a result envelope:
    #   {"success": ..., "data": ..., "findings": [...], "error": ...}
    # The envelope is transport, not a finding. Parsing it as one mints a
    # phantom "Generic finding" (severity medium) from every successful run
    # that found nothing — including reporting tools, which report on
    # findings rather than produce them. An empty list means the tool
    # genuinely found nothing.
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        return _try_json(json.dumps(data["findings"])) or []

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
        if _NEGATIVE_RESULT.match(str(title)):
            continue
        severity_raw = item.get("severity", "medium")
        confidence_raw = item.get("confidence", "medium")

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
