"""
Shared Severity Utilities — single source of truth for severity ordering
across all report generators and governance components.

Prevents drift where different report generators use independent severity
mappings that could produce contradictory results (fixes Item 35).

Usage:
    from utils.severity import SEVERITY_ORDER, severity_sort_key, count_by_severity
    sorted_findings = sorted(findings, key=severity_sort_key)
    counts = count_by_severity(findings)
"""

from __future__ import annotations

# Canonical severity ordering: lower number = more severe
SEVERITY_ORDER: dict[str, int] = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "INFO": 4,
}

SEVERITY_LEVELS: list[str] = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def normalize_severity(severity: str | None) -> str:
    """Normalize a severity string to canonical form.

    Args:
        severity: Raw severity string (e.g., "high", "High", "CRITICAL")

    Returns:
        Normalized severity in uppercase, defaults to "INFO" if unrecognized.
    """
    if not severity:
        return "INFO"
    upper = severity.upper().strip()
    return upper if upper in SEVERITY_ORDER else "INFO"


def severity_sort_key(finding: dict) -> int:
    """Sort key for findings by severity (most severe first).

    Args:
        finding: Finding dict with a 'severity' key

    Returns:
        Integer sort key (lower = more severe)
    """
    sev = normalize_severity(finding.get("severity"))
    return SEVERITY_ORDER.get(sev, 4)


def count_by_severity(findings: list[dict]) -> dict[str, int]:
    """Count findings by severity level.

    Args:
        findings: List of finding dicts

    Returns:
        Dict mapping severity level to count (all levels present)
    """
    counts = dict.fromkeys(SEVERITY_LEVELS, 0)
    for f in findings:
        sev = normalize_severity(f.get("severity"))
        if sev in counts:
            counts[sev] += 1
    return counts


def max_severity(findings: list[dict]) -> str:
    """Get the highest severity present in a list of findings.

    Args:
        findings: List of finding dicts

    Returns:
        Highest severity level found, or "INFO" if empty
    """
    if not findings:
        return "INFO"
    min_order = min(severity_sort_key(f) for f in findings)
    for sev, order in SEVERITY_ORDER.items():
        if order == min_order:
            return sev
    return "INFO"
