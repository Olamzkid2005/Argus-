"""One proof vocabulary for verification results (Stage 4.1 item 1).

The TS verifiers and the Python findings must describe a verification outcome
the same way: suspected, reproduced, not_reproduced, inconclusive, unsupported.
These tests pin the mapping and that a promoted finding carries the status,
evidence/control references and the verifier's error.
"""

from __future__ import annotations

from tools.verification.finding_promoter import promote_finding
from tools.verification.proof_status import ProofStatus, proof_status_for


class TestProofStatusMapping:
    def test_explicit_reproduction_is_reproduced(self):
        assert proof_status_for(reproduced=True) is ProofStatus.REPRODUCED

    def test_completed_negative_is_not_reproduced(self):
        assert proof_status_for(reproduced=False) is ProofStatus.NOT_REPRODUCED

    def test_no_reproduction_signal_is_only_suspected(self):
        assert proof_status_for(reproduced=None) is ProofStatus.SUSPECTED

    def test_incomplete_verification_is_inconclusive(self):
        assert (
            proof_status_for(reproduced=None, completed=False)
            is ProofStatus.INCONCLUSIVE
        )
        # A failure is not a negative, even when the verifier had reported one.
        assert (
            proof_status_for(reproduced=False, completed=False)
            is ProofStatus.INCONCLUSIVE
        )

    def test_unsupported_wins_over_every_other_signal(self):
        assert (
            proof_status_for(reproduced=True, supported=False)
            is ProofStatus.UNSUPPORTED
        )


class TestPromoterCarriesTheProof:
    def _finding(self) -> dict:
        return {"id": "f-1", "status": "PENDING", "confidence": 0.2}

    def test_high_confidence_without_reproduction_is_suspected(self):
        promoted = promote_finding(self._finding(), confidence=0.95, reproduced=None)

        assert promoted["proof_status"] == ProofStatus.SUSPECTED.value

    def test_reproduction_is_recorded_with_its_references(self):
        promoted = promote_finding(
            self._finding(),
            confidence=0.9,
            reproduced=True,
            evidence_refs=["evidence/pkg-1/har.har"],
            control_refs=["control:same-request-without-payload"],
        )

        assert promoted["proof_status"] == ProofStatus.REPRODUCED.value
        assert promoted["proof_evidence_refs"] == ["evidence/pkg-1/har.har"]
        assert promoted["proof_control_refs"] == [
            "control:same-request-without-payload"
        ]
        assert "proof_error" not in promoted

    def test_incomplete_verification_keeps_the_error(self):
        promoted = promote_finding(
            self._finding(),
            confidence=0.9,
            reproduced=None,
            completed=False,
            error="execute: navigation blocked by scope",
        )

        assert promoted["proof_status"] == ProofStatus.INCONCLUSIVE.value
        assert promoted["proof_error"] == "execute: navigation blocked by scope"

    def test_a_clean_result_clears_a_previous_error(self):
        finding = {**self._finding(), "proof_error": "stale failure"}
        promoted = promote_finding(finding, confidence=0.9, reproduced=True)

        assert "proof_error" not in promoted
