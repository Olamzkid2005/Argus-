"""Rank findings by priority using exploitability × impact × evidence."""

from __future__ import annotations

_SEVERITY_SCORE = {"CRITICAL": 10, "HIGH": 7, "MEDIUM": 4, "LOW": 2, "INFO": 1}
_TYPE_EXPLOITABILITY = {
    "SQL_INJECTION": 9, "COMMAND_INJECTION": 9, "RCE": 10,
    "XSS": 6, "STORED_XSS": 8, "SSRF": 7,
    "PRIVILEGE_ESCALATION": 8, "AUTH_BYPASS": 8,
    "DATA_EXFILTRATION": 7, "SECRET_EXPOSURE": 6,
    "CSRF": 5, "WEAK_AUTHENTICATION": 5,
    "MISCONFIGURATION": 4, "INFORMATION_DISCLOSURE": 3,
    "OPEN_REDIRECT": 4, "XXE": 6, "IDOR": 5,
}


def rank_findings(findings: list[dict]) -> list[dict]:
    """Rank findings by composite priority score.

    Score = severity_score × 0.4 + exploitability × 0.4 + confidence × 0.2
    """
    scored = []
    for f in findings:
        sev = _SEVERITY_SCORE.get(f.get("severity", "INFO"), 1)
        ftype = f.get("type", "UNKNOWN").upper().replace(" ", "_").replace("-", "_")
        exploit = _TYPE_EXPLOITABILITY.get(ftype, 3)
        confidence = float(f.get("confidence", 0.5)) * 10

        score = sev * 0.4 + exploit * 0.4 + confidence * 0.2
        scored.append({**f, "_priority_score": round(score, 2)})

    scored.sort(key=lambda x: x["_priority_score"], reverse=True)
    return scored
