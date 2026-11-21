"""The gate asks seven questions, and only one of three things can follow.

The point of the gate is that a confirmed finding and a submittable finding are
not the same thing. These tests pin the three outcomes: every question answers
``SUBMIT``; something repairable answers ``HOLD`` (evidence hygiene, missing
proof); something disqualifying answers ``DROP`` (not reproduced, self-inflicted,
duplicate, out of scope). They also pin the compatibility rule that made the
gate safe to wire into the existing report filter: a finding that was produced
before ``proof_status`` existed is held, never dropped.
"""

from __future__ import annotations

import pytest

from tools.verification.submission_gate import (
    GATE_QUESTIONS,
    Q_EVIDENCE,
    Q_HYGIENE,
    Q_IMPACT,
    Q_IN_SCOPE,
    Q_NOT_KNOWN,
    Q_NOT_SELF_INFLICTED,
    Q_REPRODUCIBLE,
    GateDecision,
    GateVerdict,
    evaluate_submission,
    gate_report_section,
)


def clean_finding(**overrides: object) -> dict:
    """A finding that passes every question, before overrides are applied."""
    finding = {
        "id": "f-1",
        "type": "SQL_INJECTION",
        "title": "SQL injection in /api/login",
        "severity": "HIGH",
        "confidence": 0.9,
        "impact": "An unauthenticated attacker can read arbitrary rows.",
        "proof_status": "reproduced",
        "request": "GET /api/login?id=1 HTTP/1.1\nHost: shop.example.com",
        "response": "HTTP/1.1 500 Internal Server Error",
        "in_scope": True,
    }
    finding.update(overrides)
    return finding


class TestSubmit:
    def test_a_fully_answered_finding_is_submittable(self):
        result = evaluate_submission(clean_finding())

        assert result.decision is GateDecision.SUBMIT
        assert result.is_submittable
        assert result.blocking == ()
        assert all(a.verdict is GateVerdict.PASS for a in result.answers)

    def test_all_seven_questions_are_always_answered(self):
        result = evaluate_submission(clean_finding())

        assert [a.question_id for a in result.answers] == [q[0] for q in GATE_QUESTIONS]

    def test_a_report_section_renders_every_answer(self):
        result = evaluate_submission(clean_finding())
        section = gate_report_section(result)

        assert "## Submission gate" in section
        assert "SUBMIT" in section
        for question_id in (Q_REPRODUCIBLE, Q_EVIDENCE, Q_IN_SCOPE):
            assert result.answer_for(question_id).question in section

    def test_to_dict_is_serialisable_and_keeps_the_audit_trail(self):
        payload = evaluate_submission(clean_finding()).to_dict()

        assert payload["decision"] == "submit"
        assert payload["blocking"] == []
        assert len(payload["answers"]) == len(GATE_QUESTIONS)
        assert set(payload["answers"][0]) == {
            "question_id",
            "question",
            "verdict",
            "reason",
        }


class TestDrop:
    @pytest.mark.parametrize("proof", ["not_reproduced", "unsupported"])
    def test_a_negative_verification_drops_the_finding(self, proof: str):
        result = evaluate_submission(clean_finding(proof_status=proof))

        assert result.decision is GateDecision.DROP
        assert Q_REPRODUCIBLE in result.blocking
        assert result.answer_for(Q_REPRODUCIBLE).verdict is GateVerdict.FAIL

    def test_a_self_inflicted_finding_drops(self):
        result = evaluate_submission(clean_finding(tags=["self-xss"]))

        assert result.decision is GateDecision.DROP
        assert Q_NOT_SELF_INFLICTED in result.blocking

    def test_an_explicit_self_inflicted_flag_drops(self):
        result = evaluate_submission(clean_finding(self_inflicted=True))

        assert result.decision is GateDecision.DROP

    def test_a_duplicate_drops(self):
        result = evaluate_submission(clean_finding(duplicate=True))

        assert result.decision is GateDecision.DROP
        assert Q_NOT_KNOWN in result.blocking

    def test_an_out_of_scope_impact_drops(self):
        result = evaluate_submission(clean_finding(out_of_scope_impact=True))

        assert result.decision is GateDecision.DROP

    def test_an_out_of_scope_target_drops(self):
        result = evaluate_submission(clean_finding(in_scope=False))

        assert result.decision is GateDecision.DROP
        assert Q_IN_SCOPE in result.blocking

    def test_a_drop_outranks_a_hold(self):
        """A blocked finding stays blocked even when other questions also fail."""
        result = evaluate_submission(
            clean_finding(proof_status="not_reproduced", confidence=0.1, request="")
        )

        assert result.decision is GateDecision.DROP


class TestHold:
    def test_evidence_with_a_session_cookie_is_held_not_dropped(self):
        result = evaluate_submission(
            clean_finding(request="GET / HTTP/1.1\nCookie: session=abc123")
        )

        assert result.decision is GateDecision.HOLD
        assert Q_HYGIENE in result.blocking
        assert result.answer_for(Q_HYGIENE).verdict is GateVerdict.FAIL

    def test_evidence_with_a_bearer_token_is_held(self):
        result = evaluate_submission(
            clean_finding(request="GET / HTTP/1.1\nAuthorization: Bearer eyJhbGciOi")
        )

        assert Q_HYGIENE in result.blocking

    def test_evidence_with_a_jwt_is_held(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = evaluate_submission(clean_finding(poc=f"token={token}"))

        assert Q_HYGIENE in result.blocking

    def test_evidence_with_victim_pii_is_held(self):
        result = evaluate_submission(
            clean_finding(response="HTTP/1.1 200 OK\n\n{\"email\": \"victim@corp.example\"}")
        )

        assert Q_HYGIENE in result.blocking

    def test_low_confidence_is_held(self):
        result = evaluate_submission(clean_finding(confidence=0.2))

        assert result.decision is GateDecision.HOLD
        assert "confidence-below-threshold" in result.blocking

    def test_no_auditable_evidence_is_held(self):
        result = evaluate_submission(clean_finding(request="", response=""))

        assert result.decision is GateDecision.HOLD
        assert result.answer_for(Q_EVIDENCE).verdict is GateVerdict.FAIL

    def test_a_missing_proof_status_is_held_not_dropped(self):
        """Findings written before the gate existed stay reportable."""
        finding = clean_finding()
        finding.pop("proof_status")

        result = evaluate_submission(finding)

        assert result.decision is GateDecision.HOLD
        assert Q_REPRODUCIBLE in result.blocking

    def test_the_reproduction_requirement_can_be_waived(self):
        """Issue classes without a verifier should not be held forever."""
        finding = clean_finding()
        finding.pop("proof_status")

        result = evaluate_submission(finding, require_reproduction=False)

        assert result.decision is GateDecision.SUBMIT

    def test_a_severity_below_the_floor_is_held(self):
        result = evaluate_submission(clean_finding(severity="LOW"))

        assert result.decision is GateDecision.HOLD
        assert result.answer_for(Q_IMPACT).verdict is GateVerdict.FAIL

    def test_an_undescribed_impact_is_unknown_not_passing(self):
        result = evaluate_submission(clean_finding(impact=""))

        assert result.answer_for(Q_IMPACT).verdict is GateVerdict.UNKNOWN


class TestReportGeneratorIntegration:
    """The report filter must drop what the gate drops, and nothing more."""

    def _generate(self, findings: list[dict]) -> str:
        from tools.bugbounty_report_generator import BugBountyReportGenerator

        return BugBountyReportGenerator().generate(findings, platform="hackerone")

    def test_a_not_reproduced_finding_is_not_reported(self):
        report = self._generate([clean_finding(proof_status="not_reproduced")])

        assert "No reportable vulnerabilities" in report

    def test_a_legacy_finding_without_proof_status_is_still_reported(self):
        finding = clean_finding()
        finding.pop("proof_status")

        report = self._generate([finding])

        assert "No reportable vulnerabilities" not in report

    def test_a_reproduced_finding_is_reported(self):
        report = self._generate([clean_finding()])

        assert "No reportable vulnerabilities" not in report
        assert "## Submission gate" not in report

    def test_a_held_finding_ships_with_the_gate_appendix(self):
        report = self._generate(
            [clean_finding(request="GET / HTTP/1.1\nCookie: session=abc123")]
        )

        assert "No reportable vulnerabilities" not in report
        assert "## Submission gate" in report
        assert "HOLD" in report
        assert Q_HYGIENE in report


class TestRobustness:
    def test_a_finding_with_no_optional_fields_does_not_raise(self):
        result = evaluate_submission({})

        assert result.decision is GateDecision.HOLD
        assert result.summary().startswith("HOLD")

    def test_a_non_numeric_confidence_does_not_raise(self):
        result = evaluate_submission(clean_finding(confidence="high"))

        assert result.decision is GateDecision.SUBMIT

    def test_evidence_lists_are_accepted_as_well_as_strings(self):
        finding = clean_finding(request="", response="", proof_evidence_refs=["shot-1.png"])

        assert evaluate_submission(finding).answer_for(Q_EVIDENCE).verdict is GateVerdict.PASS

    def test_summary_names_the_blocking_questions(self):
        summary = evaluate_submission(clean_finding(duplicate=True)).summary()

        assert summary.startswith("DROP")
        assert Q_NOT_KNOWN in summary
