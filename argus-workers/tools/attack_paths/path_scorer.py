"""Score attack paths by likelihood and impact."""

from __future__ import annotations

_SEVERITY_RANK = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1}


def score_path(path: list[str], findings: list[dict]) -> float:
    """Score a single attack path.

    Shorter paths with higher-severity findings score higher.
    """
    if not path:
        return 0.0

    total_severity = 0.0
    for node in path:
        for f in findings:
            endpoint = f.get("endpoint", "")
            from urllib.parse import urlparse

            try:
                host = urlparse(endpoint).hostname or endpoint
            except Exception:
                host = endpoint
            if f"host:{host}" == node:
                total_severity += _SEVERITY_RANK.get(f.get("severity", "INFO"), 1)

    length_penalty = max(0.1, 1.0 / len(path))
    return round(total_severity * length_penalty, 2)


def rank_paths(
    paths: list[list[str]],
    findings: list[dict],
) -> list[dict]:
    """Rank attack paths by composite score.

    Returns list of dicts with path, score, and step count.
    """
    scored = []
    for path in paths:
        s = score_path(path, findings)
        scored.append(
            {
                "path": path,
                "score": s,
                "steps": len(path),
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
