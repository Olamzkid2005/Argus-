"""Confidence scoring for verification results."""

from __future__ import annotations


def score_confidence(finding: dict, reproduction_result: dict, evidence: dict) -> float:
    """Score the confidence of a finding based on verification evidence.

    The score describes how strongly the finding is believed; it is not a proof
    claim (Stage 4.1). Two structural facts drive it:

    * ``supported`` — False for placeholder strategies that never replayed the
      attack. Those cannot add an evidence bonus, however many artifacts the
      collector wrote, and they are not penalised either: nothing was learned.
    * ``reproduced`` — only a real replay raises the score, carrying the
      ``ProofStatus.REPRODUCED`` claim.

    Returns a float between 0.0 and 1.0.
    """
    base_confidence = float(finding.get("confidence", 0.5))

    if not reproduction_result.get("supported", True):
        # No real verification was attempted for this issue type. Descriptor or
        # error artifacts are not evidence, so the score stays where it was.
        return base_confidence

    if reproduction_result.get("reproduced"):
        return min(1.0, base_confidence + 0.3)

    if reproduction_result.get("error"):
        return base_confidence

    evidence_count = len(evidence.get("artifacts", []))
    if evidence_count > 0:
        evidence_bonus = min(0.15, evidence_count * 0.05)
        return min(0.9, base_confidence + evidence_bonus)

    return max(0.1, base_confidence - 0.2)
