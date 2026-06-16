import csv
import io
import json
import re

from ..normalizer import normalize_severity
from ..types import NormalizedFinding


def _infer_severity(msg: str) -> int:
    msg_lower = msg.lower()
    if re.search(r"\bcritical\b", msg_lower):
        return 4
    if re.search(r"\bhigh\b", msg_lower):
        return 3
    if re.search(r"\bmedium\b", msg_lower):
        return 2
    if re.search(r"\b(?:info|note)\b", msg_lower):
        return 0
    return 2


def _parse_json(output: str) -> list[NormalizedFinding]:
    findings = []
    try:
        items = json.loads(output)
    except json.JSONDecodeError:
        return findings

    if not isinstance(items, list):
        items = [items]

    for item in items:
        if not isinstance(item, dict):
            continue
        msg = item.get("msg", "") or item.get("description", "")
        osvdb = item.get("OSVDB", "") or item.get("osvdb", "")
        url = item.get("url", "") or item.get("hostname", "")

        findings.append(NormalizedFinding(
            title=msg[:120] if msg else "Nikto finding",
            severity=_infer_severity(msg),
            confidence=2,
            description=f"OSVDB: {osvdb}" if osvdb else msg,
            tool="nikto",
            evidence=[{
                "type": "http",
                "url": url,
                "osvdb": osvdb,
                "message": msg,
            }],
            subtype="web_vulnerability",
        ))

    return findings


def _parse_csv(output: str) -> list[NormalizedFinding]:
    findings = []
    reader = csv.reader(io.StringIO(output))
    for row in reader:
        if not row or len(row) < 5:
            continue
        hostname = row[0].strip()
        port = row[1].strip() if len(row) > 1 else ""
        osvdb = row[2].strip() if len(row) > 2 else ""
        method = row[3].strip() if len(row) > 3 else ""
        url = row[4].strip() if len(row) > 4 else ""
        description = row[5].strip() if len(row) > 5 else ""

        findings.append(NormalizedFinding(
            title=description[:120] if description else "Nikto finding",
            severity=normalize_severity("medium", 2),
            confidence=2,
            description=f"{method} {url}: {description}",
            tool="nikto",
            evidence=[{
                "type": "http",
                "hostname": hostname,
                "port": port,
                "osvdb": osvdb,
                "method": method,
                "url": url,
                "description": description,
            }],
            subtype="web_vulnerability",
        ))

    return findings


def _parse_text(output: str) -> list[NormalizedFinding]:
    findings = []
    pattern = re.compile(r"^[-+]\s+(.*)", re.MULTILINE)
    for match in pattern.finditer(output):
        content = match.group(1).strip()
        if not content or len(content) < 10:
            continue
        findings.append(NormalizedFinding(
            title=content[:120],
            severity=_infer_severity(content),
            confidence=1,
            description=content,
            tool="nikto",
            evidence=[{"type": "text", "content": content}],
            subtype="web_vulnerability",
        ))
    return findings


def parse(output: str) -> list[NormalizedFinding]:
    if not output or not output.strip():
        return []

    findings = _parse_json(output)
    if findings:
        return findings

    findings = _parse_csv(output)
    if findings:
        return findings

    return _parse_text(output)
