"""Promote or reject findings based on verification evidence."""

from __future__ import annotations

import logging

from tools.verification.proof_status import (
    ProofResult,
    ProofStatus,
    proof_status_for,
)

logger = logging.getLogger(__name__)


def promote_finding(
    finding: dict,
    confidence: float,
    reproduced: bool | None,
    *,
    completed: bool = True,
    supported: bool = True,
    evidence_refs: list[str] | tuple[str, ...] = (),
    control_refs: list[str] | tuple[str, ...] = (),
    error: str | None = None,
) -> dict:
    """Update a finding's status based on verification results.

    The finding always carries an explicit ``proof_status`` from the shared
    vocabulary (Stage 4.1), with the evidence/control references and, when the
    verification could not complete, the verifier's error. ``confidence`` no
    longer decides the proof claim by itself: a high score without a
    reproduction is only ``suspected``.

    Returns the updated finding dict.
    """
    updated = dict(finding)
    updated["confidence"] = confidence

    proof = ProofResult(
        status=proof_status_for(
            reproduced=reproduced, completed=completed, supported=supported
        ),
        evidence_refs=tuple(evidence_refs),
        control_refs=tuple(control_refs),
        error=error,
    )
    updated["proof_status"] = str(proof.status)
    updated["proof_evidence_refs"] = list(proof.evidence_refs)
    updated["proof_control_refs"] = list(proof.control_refs)
    if proof.error:
        updated["proof_error"] = proof.error
    elif "proof_error" in updated:
        updated.pop("proof_error")

    if proof.status is ProofStatus.REPRODUCED and (proof.evidence_refs or proof.control_refs):
        # Confirmation needs a reproduction *and* something to audit: an
        # evidence reference or a control comparison. A reproduction with no
        # captured proof is a claim, not a confirmation.
        updated["status"] = "CONFIRMED"
        updated["verification"] = "REPRODUCED"
        logger.info("Finding %s CONFIRMED (reproduced)", finding.get("id", "unknown"))
    elif confidence >= 0.4:
        # Confidence no longer confirms on its own: metadata and error-artifact
        # scores stop at PENDING, which is why a failed verification cannot be
        # promoted by calling this again with the same inputs.
        updated["status"] = "PENDING"
        updated["verification"] = "NEEDS_REVIEW"
        logger.info(
            "Finding %s PENDING (confidence %.2f, proof %s)",
            finding.get("id", "unknown"),
            confidence,
            proof.status,
        )
    else:
        updated["status"] = "REJECTED"
        updated["verification"] = "LOW_CONFIDENCE"
        logger.info(
            "Finding %s REJECTED (low confidence %.2f)",
            finding.get("id", "unknown"),
            confidence,
        )

    return updated
