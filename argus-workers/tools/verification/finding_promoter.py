"""Promote or reject findings based on verification evidence."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def promote_finding(finding: dict, confidence: float, reproduced: bool) -> dict:
    """Update a finding's status based on verification results.

    Returns the updated finding dict.
    """
    updated = dict(finding)
    updated["confidence"] = confidence

    if reproduced:
        updated["status"] = "CONFIRMED"
        updated["verification"] = "REPRODUCED"
        logger.info("Finding %s CONFIRMED (reproduced)", finding.get("id", "unknown"))
    elif confidence >= 0.7:
        updated["status"] = "CONFIRMED"
        updated["verification"] = "HIGH_CONFIDENCE"
        logger.info(
            "Finding %s CONFIRMED (high confidence %.2f)",
            finding.get("id", "unknown"),
            confidence,
        )
    elif confidence >= 0.4:
        updated["status"] = "PENDING"
        updated["verification"] = "NEEDS_REVIEW"
        logger.info(
            "Finding %s PENDING (confidence %.2f)",
            finding.get("id", "unknown"),
            confidence,
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
