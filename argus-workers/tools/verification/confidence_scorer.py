"""Confidence scoring for verification results."""

from __future__ import annotations


def score_confidence(finding: dict, reproduction_result: dict, evidence: dict) -> float:
    """Score the confidence of a finding based on verification evidence.

    Returns a float between 0.0 and 1.0.
    """
    base_confidence = float(finding.get("confidence", 0.5))

    if reproduction_result.get("reproduced"):
        return min(1.0, base_confidence + 0.3)

    evidence_count = len(evidence.get("artifacts", []))
    if evidence_count > 0:
        evidence_bonus = min(0.15, evidence_count * 0.05)
        return min(0.9, base_confidence + evidence_bonus)

    error = reproduction_result.get("error", "")
    if "Requires live HTTP client" in error:
        return base_confidence

    return max(0.1, base_confidence - 0.2)
