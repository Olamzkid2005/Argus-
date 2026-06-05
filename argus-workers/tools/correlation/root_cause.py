"""Group findings by their underlying root cause."""

from __future__ import annotations

from collections import defaultdict


_SEVERITY_RANK = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1}


def _root_cause_key(finding: dict) -> str:
    """Derive a root-cause key from a finding.

    Uses CWE if present, otherwise falls back to finding type + endpoint host.
    """
    cwe = finding.get("cwe") or finding.get("cwe_id") or ""
    if cwe:
        return f"cwe:{cwe}"

    endpoint = finding.get("endpoint", "")
    ftype = finding.get("type", "UNKNOWN")

    from urllib.parse import urlparse
    try:
        host = urlparse(endpoint).hostname or endpoint
    except Exception:
        host = endpoint

    return f"type:{ftype}:host:{host}"


def group_by_root_cause(findings: list[dict]) -> dict[str, list[dict]]:
    """Group findings by root cause.

    Returns dict mapping root_cause_key → list of related findings.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        key = _root_cause_key(f)
        groups[key].append(f)
    return dict(groups)


def find_root_causes(findings: list[dict], min_group_size: int = 2) -> list[dict]:
    """Identify root causes that account for multiple findings.

    Returns list of root cause summaries sorted by severity impact.
    """
    groups = group_by_root_cause(findings)
    root_causes = []

    for key, group in groups.items():
        if len(group) < min_group_size:
            continue

        max_severity = max(
            (_SEVERITY_RANK.get(f.get("severity", "INFO"), 0) for f in group),
            default=0,
        )
        severity_name = {v: k for k, v in _SEVERITY_RANK.items()}.get(max_severity, "INFO")

        root_causes.append({
            "root_cause": key,
            "finding_count": len(group),
            "max_severity": severity_name,
            "affected_endpoints": list({
                f.get("endpoint", "") for f in group if f.get("endpoint")
            }),
            "finding_ids": [f.get("id", f.get("type", "")) for f in group],
        })

    root_causes.sort(key=lambda rc: _SEVERITY_RANK.get(rc["max_severity"], 0), reverse=True)
    return root_causes
