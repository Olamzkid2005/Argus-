"""The score describes belief, and placeholders earn nothing (Stage 4.1 item 3).

A placeholder reproduction strategy used to be detected by searching its error
text for "Requires live HTTP client" — string matching that broke the moment a
message changed. The result now carries a structural `supported` flag, and an
unsupported result cannot buy confidence from the descriptor artifacts it wrote.
"""

import pytest

from tools.verification.confidence_scorer import score_confidence


class TestScoreConfidence:
    """Tests for the score_confidence function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            score_confidence()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            score_confidence()


class TestScoreValues:
    def test_a_reproduction_raises_the_score(self):
        score = score_confidence(
            {"confidence": 0.5}, {"reproduced": True, "supported": True}, {}
        )

        assert score == pytest.approx(0.8)

    def test_an_unsupported_placeholder_adds_no_bonus(self):
        """Canned artifacts from a placeholder are not evidence."""
        score = score_confidence(
            {"confidence": 0.5},
            {"reproduced": False, "supported": False, "error": "Requires live HTTP client"},
            {"artifacts": [{"path": "evidence.json"}, {"path": "error.txt"}]},
        )

        assert score == pytest.approx(0.5)

    def test_an_unsupported_placeholder_is_not_penalised_either(self):
        score = score_confidence(
            {"confidence": 0.5}, {"reproduced": False, "supported": False}, {}
        )

        assert score == pytest.approx(0.5)

    def test_a_supported_attempt_with_artifacts_earns_a_bonus(self):
        score = score_confidence(
            {"confidence": 0.5},
            {"reproduced": False, "supported": True},
            {"artifacts": [{"path": "response.html"}]},
        )

        assert score == pytest.approx(0.55)

    def test_a_supported_negative_without_evidence_loses_confidence(self):
        score = score_confidence(
            {"confidence": 0.5}, {"reproduced": False, "supported": True}, {}
        )

        assert score == pytest.approx(0.3)

    def test_an_error_without_the_legacy_phrase_does_not_add_confidence(self):
        """Structured `supported` replaces matching on the error message."""
        score = score_confidence(
            {"confidence": 0.5},
            {"reproduced": False, "supported": True, "error": "connection reset"},
            {"artifacts": [{"path": "error.txt"}]},
        )

        assert score == pytest.approx(0.5)
