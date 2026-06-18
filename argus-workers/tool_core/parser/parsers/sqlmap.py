import json
import re

from ..types import NormalizedFinding


def _classify_technique(title: str) -> str:
    t = title.lower()
    if "boolean" in t:
        return "SQL_INJECTION_BOOLEAN_BLIND"
    if "time" in t:
        return "SQL_INJECTION_TIME_BLIND"
    if "union" in t:
        return "SQL_INJECTION_UNION"
    if "error" in t:
        return "SQL_INJECTION_ERROR"
    if "stacked" in t:
        return "SQL_INJECTION_STACKED"
    return "SQL_INJECTION"


def _parse_json(output: str) -> list[NormalizedFinding]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []

    findings = []
    entries = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("data", data.get("entries", [data]))

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
                title = param_info.get("title", "SQL injection")
                payload = param_info.get("payload", "")
                vuln_type = _classify_technique(title)

                findings.append(
                    NormalizedFinding(
                        title=title,
                        severity=4,
                        confidence=5,
                        description=f"SQL injection in parameter '{param_name}' at {url}",
                        tool="sqlmap",
                        evidence=[
                            {
                                "type": "http",
                                "url": url,
                                "parameter": param_name,
                                "payload": payload,
                                "technique": vuln_type,
                            }
                        ],
                        subtype=vuln_type,
                    )
                )

    return findings


def _parse_text(output: str) -> list[NormalizedFinding]:
    findings = []
    if "sqlmap identified the following injection point" in output.lower():
        url_match = re.search(r"(https?://[^\s]+)", output)
        endpoint = url_match.group(1) if url_match else "unknown_target"

        findings.append(
            NormalizedFinding(
                title="SQL injection detected",
                severity=4,
                confidence=4,
                description=f"sqlmap identified an injection point at {endpoint}",
                tool="sqlmap",
                evidence=[{"type": "text", "content": output[:1000]}],
                subtype="SQL_INJECTION",
            )
        )

    return findings


def parse(output: str) -> list[NormalizedFinding]:
    if not output or not output.strip():
        return []

    findings = _parse_json(output)
    if findings:
        return findings

    return _parse_text(output)
