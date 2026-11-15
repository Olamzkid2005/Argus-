"""Promotion is decided on proof, never on a score (Stage 4.1 item 2).

A finding may only reach CONFIRMED when the verification explicitly reproduced
it *and* left something to audit — an evidence reference or a control
comparison. Confidence, metadata and error artifacts stop at PENDING, and a
failed/inconclusive/unsupported verification cannot be promoted by calling the
promoter again.
"""

import pytest

from tools.verification.finding_promoter import promote_finding


def make_finding() -> dict:
    return {"id": "f-1", "status": "PENDING", "confidence": 0.2}


class TestPromoteFindingShape:
    """Tests for the promote_finding function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            promote_finding()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            promote_finding()


class TestConfidenceCannotConfirm:
    def test_high_confidence_without_reproduction_stays_pending(self):
        promoted = promote_finding(make_finding(), confidence=0.9, reproduced=None)

        assert promoted["status"] == "PENDING"
        assert promoted["verification"] == "NEEDS_REVIEW"
        assert promoted["proof_status"] == "suspected"

    def test_high_confidence_with_an_error_artifact_stays_pending(self):
        """A 0.9 score backed by captured artifacts is still not a proof claim."""
        promoted = promote_finding(
            make_finding(),
            confidence=0.95,
            reproduced=None,
            evidence_refs=["evidence/pkg-1/error-page.html"],
        )

        assert promoted["status"] == "PENDING"

    def test_repeated_promotion_cannot_walk_a_suspected_finding_up(self):
        finding = make_finding()
        for _ in range(5):
            finding = promote_finding(finding, confidence=0.95, reproduced=None)

        assert finding["status"] == "PENDING"


class TestProofConfirms:
    def test_reproduction_with_evidence_is_confirmed(self):
        promoted = promote_finding(
            make_finding(),
            confidence=0.5,
            reproduced=True,
            evidence_refs=["evidence/pkg-1/har.har"],
        )

        assert promoted["status"] == "CONFIRMED"
        assert promoted["verification"] == "REPRODUCED"

    def test_reproduction_with_a_control_is_confirmed(self):
        promoted = promote_finding(
            make_finding(),
            confidence=0.5,
            reproduced=True,
            control_refs=["control:same-request-without-payload"],
        )

        assert promoted["status"] == "CONFIRMED"

    def test_reproduction_with_nothing_to_audit_stays_pending(self):
        promoted = promote_finding(make_finding(), confidence=0.95, reproduced=True)

        assert promoted["status"] == "PENDING"
        assert promoted["proof_status"] == "reproduced"


class TestFailedVerificationCannotBeOverridden:
    @pytest.mark.parametrize(
        "completed, supported, expected",
        [
            (True, True, "not_reproduced"),
            (False, True, "inconclusive"),
            (True, False, "unsupported"),
        ],
    )
    def test_never_confirms_even_with_high_confidence_and_evidence(
        self, completed, supported, expected
    ):
        finding = make_finding()
        for _ in range(5):
            finding = promote_finding(
                finding,
                confidence=0.99,
                reproduced=False if completed and supported else None,
                completed=completed,
                supported=supported,
                evidence_refs=["evidence/pkg-1/har.har"],
                control_refs=["control:second-identity"],
            )

        assert finding["status"] == "PENDING"
        assert finding["proof_status"] == expected


class TestLowConfidenceRejection:
    def test_low_confidence_without_proof_is_rejected(self):
        promoted = promote_finding(make_finding(), confidence=0.1, reproduced=None)

        assert promoted["status"] == "REJECTED"
        assert promoted["verification"] == "LOW_CONFIDENCE"
