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

#: A verifier that found nothing still prints a titled result. That result is
#: not a finding; promoting it made every clean run look like it had a MEDIUM.
_NEGATIVE_RESULT = re.compile(
    r"^no\b.*\b(detected|found|identified|discovered)\b", re.IGNORECASE
)


_HEADLINE_FIELDS = (
    "title",
    "name",
    "message",
    "finding",
    "description",
    "detail",
    "issue",
    "check",
    "reason",
    "summary",
    "path",
)


_STATEMENT_FIELDS = (
    "title",
    "name",
    "message",
    "finding",
    "description",
    "detail",
    "issue",
    "check",
    "reason",
    "summary",
)

#: Types that say nothing about what was found; a finding carrying one of these
#: still needs a sentence to be a finding.
_CONTENTLESS_TYPES = {"", "GENERIC_FINDING", "RAW_OUTPUT", "UNKNOWN"}


def _states_a_finding(item: dict) -> bool:
    """Does this item say anything about what was found?

    A verifier that emits ``{"severity": 2, "confidence": 3}`` — or one with
    only a target URL — has not reported a finding, and turning it into
    "unknown: finding" / "Finding at <host>" put thirteen MEDIUM findings with
    no content into the testasp.vulnweb.com report. Requiring a sentence (or an
    explicit finding type) keeps those out without dropping real results.
    """
    for key in _STATEMENT_FIELDS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return True
    finding_type = str(item.get("type") or "").strip().upper()
    return finding_type not in _CONTENTLESS_TYPES

def _headline_from_item(item: dict) -> str:
    """Return a headline for an item that may not carry a title.

    Findings without a title used to land as "Generic finding", which tells an
    operator nothing and made a report unreadable. The text the tool did provide
    is a better headline than a placeholder; when there is no text at all the
    tool and its type are still more informative than "Generic finding".
    """
    for key in _HEADLINE_FIELDS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            line = value.strip().splitlines()[0].strip()
            if line:
                return line[:120]
    url = item.get("url") or item.get("endpoint")
    endpoint = url.strip() if isinstance(url, str) and url.strip() else ""
    finding_type = str(item.get("type") or item.get("subtype") or "").strip()
    if finding_type and finding_type.upper() not in _CONTENTLESS_TYPES:
        label = finding_type.replace("_", " ").strip()
        label = label[:1].upper() + label[1:].lower()
        return f"{label}: {endpoint}"[:120] if endpoint else label[:120]
    if endpoint:
        return f"Finding at {endpoint}"[:120]
    tool = str(item.get("tool") or "unknown").strip()
    subtype = str(item.get("type") or item.get("subtype") or "finding").replace("_", " ").strip()
    return f"{tool}: {subtype}"[:120]


def _try_json(output: str) -> list[NormalizedFinding] | None:
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
        if not _states_a_finding(item):
            continue
        title = _headline_from_item(item)
        if _NEGATIVE_RESULT.match(str(title)):
            continue
        findings.append(
            NormalizedFinding(
                title=str(title),
                severity=normalize_severity(item.get("severity", "medium")),
                confidence=normalize_confidence(item.get("confidence", "medium")),
                description=str(item.get("description") or item.get("message") or title),
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

    # No last-resort "Raw output captured" finding. It was an INFO entry whose
    # description said the output was stored as evidence, but nothing stored it,
    # so every unparsed tool produced a finding that pointed at nothing — one
    # appeared in the testasp.vulnweb.com report from the cloud phase. Output no
    # parser can read is a coverage gap, reported by the phase, not a finding.

    return findings


def parse(output: str) -> list[NormalizedFinding]:
    if not output or not output.strip():
        return []

    # JSON is authoritative: a parsed empty result means the tool found
    # nothing, and must not fall through to the regex heuristics (which would
    # otherwise turn the JSON envelope's own "error": "" key into findings).
    json_findings = _try_json(output)
    if json_findings is not None:
        return json_findings

    return _regex_extract(output)
