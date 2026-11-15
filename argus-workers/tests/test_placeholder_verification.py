"""Placeholder reproduction cannot confirm a finding, end to end (Stage 4.1 item 3).

This exercises the exact worker pipeline the verification agent runs —
reproduction engine -> evidence collector -> confidence scorer -> finding
promoter — with the same wiring, and shows that:

* a placeholder strategy lands on `unsupported` and stays PENDING, no matter
  how high the score or how many descriptor artifacts were written;
* a supported reproduction with real evidence still confirms, so the guard is
  not a blanket refusal.
"""

from tools.verification.confidence_scorer import score_confidence
from tools.verification.evidence_collector import VerificationEvidenceCollector
from tools.verification.finding_promoter import promote_finding
from tools.verification.reproduction_engine import ReproductionEngine


def run_pipeline(engine, collector, finding, reproduction):
    evidence = collector.collect(finding, reproduction)
    confidence = score_confidence(finding, reproduction, evidence)
    proof_artifacts = [
        artifact["path"]
        for artifact in evidence.get("artifacts", [])
        if artifact.get("type") != "error_log" and artifact.get("path")
    ]
    promoted = promote_finding(
        finding,
        confidence,
        reproduction.get("reproduced", False),
        supported=reproduction.get("supported", True),
        completed=not reproduction.get("error"),
        evidence_refs=proof_artifacts,
        error=reproduction.get("error"),
    )
    return promoted, evidence, confidence


class TestPlaceholderCannotConfirm:
    def test_placeholder_reproduction_stays_unsupported_and_pending(self, tmp_path):
        engine = ReproductionEngine()
        collector = VerificationEvidenceCollector(output_dir=str(tmp_path))
        finding = {"id": "f-1", "type": "SQL_INJECTION", "confidence": 0.9}

        promoted, evidence, confidence = run_pipeline(
            engine,
            collector,
            finding,
            engine.reproduce(finding, "https://example.com"),
        )

        # The collector did write artifacts (evidence.json + error.txt), and the
        # score did not move — descriptor artifacts are not proof.
        assert evidence["artifacts"]
        assert confidence == 0.9
        assert promoted["proof_status"] == "unsupported"
        assert promoted["status"] == "PENDING"
        assert promoted["proof_error"]

    def test_repeated_promotion_of_a_placeholder_never_confirms(self, tmp_path):
        engine = ReproductionEngine()
        collector = VerificationEvidenceCollector(output_dir=str(tmp_path))
        finding = {"id": "f-2", "type": "XSS", "confidence": 0.9}

        promoted, _, _ = run_pipeline(
            engine,
            collector,
            finding,
            engine.reproduce(finding, "https://example.com"),
        )
        for _ in range(5):
            promoted = promote_finding(
                promoted,
                0.99,
                False,
                supported=False,
                evidence_refs=promoted["proof_evidence_refs"],
            )

        assert promoted["status"] == "PENDING"
        assert promoted["proof_status"] == "unsupported"


class TestRealReproductionStillConfirms:
    def test_supported_reproduction_with_evidence_confirms(self, tmp_path):
        collector = VerificationEvidenceCollector(output_dir=str(tmp_path))
        finding = {"id": "f-3", "type": "XSS", "confidence": 0.5}
        reproduction = {
            "reproduced": True,
            "supported": True,
            "evidence": {"alert_fired": True, "payload": "<img src=x onerror=alert(1)>"},
        }

        promoted, evidence, confidence = run_pipeline(
            collector=collector, engine=None, finding=finding, reproduction=reproduction
        )

        assert evidence["artifacts"]
        assert confidence == 0.8
        assert promoted["proof_status"] == "reproduced"
        assert promoted["status"] == "CONFIRMED"
