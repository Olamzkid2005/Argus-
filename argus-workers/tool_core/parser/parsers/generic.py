import json
import re
from typing import Any

from ..normalizer import normalize_confidence, normalize_severity
from ..types import NormalizedFinding

_URL_PATTERN = re.compile(r"https?://[^\s\"'>)]+")
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_ERROR_PATTERN = re.compile(
    r"(error|fail|critical|vulnerability|warning)\s*[:]?\s*(.*)", re.IGNORECASE
)


def _try_json(output: str) -> list[NormalizedFinding] | None:
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
        findings.append(
            NormalizedFinding(
                title=str(title),
                severity=normalize_severity(str(item.get("severity", "medium"))),
                confidence=normalize_confidence(str(item.get("confidence", "medium"))),
                description=str(item.get("description", item.get("message", ""))),
                tool=item.get("tool", "unknown"),
                evidence=[item],
            )
        )
    return findings


def _regex_extract(output: str) -> list[NormalizedFinding]:
    findings = []

    urls = _URL_PATTERN.findall(output)
    ips = _IP_PATTERN.findall(output)
    cves = _CVE_PATTERN.findall(output)

    evidence: list[dict[str, Any]] = []
    if urls:
        evidence.append({"type": "urls", "content": list(set(urls))})
    if ips:
        evidence.append({"type": "ips", "content": list(set(ips))})
    if cves:
        evidence.append({"type": "cves", "content": list(set(cves))})

    if cves:
        for cve in set(cves):
            findings.append(
                NormalizedFinding(
                    title=f"CVE referenced: {cve}",
                    severity=2,
                    confidence=1,
                    description=f"Found reference to {cve} in tool output",
                    tool="unknown",
                    cve=cve,
                    evidence=[{"type": "cve", "content": cve}],
                    subtype="cve_reference",
                )
            )

    error_matches = _ERROR_PATTERN.findall(output)
    if error_matches and not (urls or ips or cves):
        for severity_tag, msg in error_matches[:5]:
            sev = normalize_severity(severity_tag, 2)
            findings.append(
                NormalizedFinding(
                    title=msg.strip()[:120] or f"Pattern: {severity_tag}",
                    severity=sev,
                    confidence=1,
                    description=msg.strip(),
                    tool="unknown",
                    evidence=[{"type": "text", "content": msg.strip()}],
                )
            )

    if not findings and output.strip():
        findings.append(
            NormalizedFinding(
                title="Raw output captured",
                severity=0,
                confidence=1,
                description="No structured parsing available; raw output stored as evidence",
                tool="unknown",
                evidence=[{"type": "raw", "content": output[:2000]}],
                subtype="raw_output",
            )
        )

    return findings


def parse(output: str) -> list[NormalizedFinding]:
    if not output or not output.strip():
        return []

    json_findings = _try_json(output)
    if json_findings:
        return json_findings

    return _regex_extract(output)
