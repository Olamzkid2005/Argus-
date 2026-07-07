"""Tests for models — CandidateList, Feedback, ConfidenceScorer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from models.candidate_list import (
    SOURCE_QUALITY,
    Candidate,
    CandidateList,
    CandidateSource,
    _map_tool_to_source,
)
from models.confidence_scorer import ConfidenceScorer
from models.feedback import FeedbackLearningLoop, FindingFeedback

# ═══════════════════════════════════════════════════════════════════════════════
# CandidateList Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCandidateSource:
    """Tests for CandidateSource enum."""

    def test_enum_values(self):
        assert CandidateSource.NUCLEI_CVE == "nuclei_cve"
        assert CandidateSource.DALFOX == "dalfox"
        assert CandidateSource.SQLMAP == "sqlmap"
        assert CandidateSource.RECON_ENDPOINT == "recon_endpoint"

    def test_all_sources_have_quality(self):
        for source in CandidateSource:
            assert source in SOURCE_QUALITY


class TestCandidate:
    """Tests for Candidate dataclass."""

    def test_init_sets_fields(self):
        c = Candidate(
            endpoint="https://example.com",
            source=CandidateSource.NUCLEI_CVE,
            vuln_slug="sql-injection",
            snippet="Found SQL injection payload",
            line_hint="line 42",
            confidence=0.85,
        )
        assert c.endpoint == "https://example.com"
        assert c.source == CandidateSource.NUCLEI_CVE
        assert c.vuln_slug == "sql-injection"
        assert c.snippet == "Found SQL injection payload"
        assert c.line_hint == "line 42"
        assert c.confidence == 0.85

    def test_default_confidence(self):
        c = Candidate(
            endpoint="https://example.com",
            source=CandidateSource.DALFOX,
            vuln_slug="xss",
            snippet="XSS detected",
        )
        assert c.confidence == 0.5
        assert c.line_hint is None

    def test_from_finding_creates_candidate(self):
        finding = {
            "source_tool": "nuclei",
            "endpoint": "https://example.com",
            "type": "SQL_INJECTION",
            "evidence": {"matched_text": "1=1"},
            "confidence": 0.9,
        }
        c = Candidate.from_finding(finding)
        assert c.endpoint == "https://example.com"
        assert c.source == CandidateSource.NUCLEI_CVE
        assert c.vuln_slug == "sql-injection"
        assert c.snippet == "1=1"
        assert c.confidence == 0.9

    def test_from_finding_falls_back_to_tool_key(self):
        finding = {
            "tool": "dalfox",
            "endpoint": "https://example.com",
            "type": "XSS",
            "evidence": {"message": "DOM XSS"},
        }
        c = Candidate.from_finding(finding)
        assert c.source == CandidateSource.DALFOX
        assert c.snippet == "DOM XSS"
        assert c.vuln_slug == "xss"

    def test_from_finding_handles_missing_fields(self):
        finding = {}
        c = Candidate.from_finding(finding)
        assert c.endpoint == ""
        assert c.source == CandidateSource.RECON_ENDPOINT
        assert c.vuln_slug == "unknown"
        assert c.snippet == ""

    def test_from_finding_raises_on_string_evidence(self):
        finding = {
            "source_tool": "nuclei",
            "endpoint": "https://example.com",
            "type": "XSS",
            "evidence": "raw string evidence",
        }
        with pytest.raises(AttributeError):
            Candidate.from_finding(finding)


class TestCandidateList:
    """Tests for CandidateList dataclass."""

    def test_init_sets_fields(self):
        cl = CandidateList(target="https://example.com")
        assert cl.target == "https://example.com"
        assert cl.candidates == []

    def test_from_findings_builds_candidate_list(self):
        findings = [
            {
                "source_tool": "nuclei",
                "endpoint": "https://example.com",
                "type": "XSS",
                "evidence": {},
            },
            {
                "source_tool": "dalfox",
                "endpoint": "https://example.com",
                "type": "XSS",
                "evidence": {},
            },
        ]
        cl = CandidateList.from_findings("https://example.com", findings)
        assert cl.target == "https://example.com"
        assert len(cl.candidates) == 2
        assert all(isinstance(c, Candidate) for c in cl.candidates)

    def test_from_findings_empty_findings(self):
        cl = CandidateList.from_findings("https://example.com", [])
        assert len(cl.candidates) == 0

    def test_by_quality_returns_sorted_candidates(self):
        c1 = Candidate(
            "https://example.com", CandidateSource.RECON_ENDPOINT, "xss", "hit"
        )
        c2 = Candidate(
            "https://example.com", CandidateSource.NUCLEI_CVE, "sql-injection", "hit"
        )
        c3 = Candidate("https://example.com", CandidateSource.DALFOX, "xss", "hit")
        cl = CandidateList(target="https://example.com", candidates=[c1, c2, c3])
        sorted_c = cl.by_quality()
        assert sorted_c[0].source == CandidateSource.NUCLEI_CVE  # highest priority
        assert sorted_c[-1].source == CandidateSource.RECON_ENDPOINT  # lowest priority

    def test_by_quality_unknown_source_sorted_last(self):
        c1 = Candidate(
            "https://example.com", CandidateSource.RECON_ENDPOINT, "xss", "hit"
        )
        c2 = Candidate("https://example.com", CandidateSource.NUCLEI_CVE, "xss", "hit")
        cl = CandidateList(target="https://example.com", candidates=[c1, c2])
        sorted_c = cl.by_quality()
        assert sorted_c[0].source == CandidateSource.NUCLEI_CVE

    def test_to_llm_summary_empty_candidates(self):
        cl = CandidateList(target="https://example.com")
        assert cl.to_llm_summary() == ""

    def test_to_llm_summary_with_candidates(self):
        c1 = Candidate(
            "https://example.com", CandidateSource.NUCLEI_CVE, "sql-injection", "hit"
        )
        c2 = Candidate("https://example.com", CandidateSource.DALFOX, "xss", "hit")
        cl = CandidateList(target="https://example.com", candidates=[c1, c2])
        summary = cl.to_llm_summary()
        assert "SCAN CANDIDATES" in summary
        assert "sql-injection" in summary
        assert "xss" in summary
        assert "2 total" in summary

    def test_to_llm_summary_deduplicates_endpoints(self):
        c1 = Candidate(
            "https://example.com/a", CandidateSource.NUCLEI_CVE, "xss", "hit"
        )
        c2 = Candidate("https://example.com/b", CandidateSource.DALFOX, "xss", "hit")
        cl = CandidateList(target="https://example.com", candidates=[c1, c2])
        summary = cl.to_llm_summary()
        assert "2 hit(s)" in summary


class TestMapToolToSource:
    """Tests for _map_tool_to_source()."""

    def test_maps_known_tools(self):
        assert _map_tool_to_source("nuclei") == CandidateSource.NUCLEI_CVE
        assert _map_tool_to_source("dalfox") == CandidateSource.DALFOX
        assert _map_tool_to_source("sqlmap") == CandidateSource.SQLMAP
        assert _map_tool_to_source("httpx") == CandidateSource.RECON_ENDPOINT
        assert _map_tool_to_source("semgrep") == CandidateSource.CUSTOM_RULE

    def test_unknown_tool_defaults_to_recon_endpoint(self):
        assert _map_tool_to_source("unknown_tool") == CandidateSource.RECON_ENDPOINT


# ═══════════════════════════════════════════════════════════════════════════════
# ConfidenceScorer Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfidenceScorer:
    """Tests for ConfidenceScorer."""

    def test_weights_sum_to_one(self):
        total = sum(ConfidenceScorer.WEIGHTS.values())
        assert abs(total - 1.0) < 0.01

    def test_score_returns_legacy_when_feature_disabled(self):
        with patch("models.confidence_scorer.is_enabled", return_value=False):
            scorer = ConfidenceScorer()
            finding = {
                "tool_agreement_level": 0.8,
                "evidence_strength": 0.7,
                "fp_likelihood": 0.2,
            }
            score = scorer.score(finding)
            assert 0.0 <= score <= 1.0

    def test_legacy_score_formula(self):
        score = ConfidenceScorer.compute(0.8, 0.7, 0.2)
        expected = (0.8 * 0.7) / (1 + 0.2)
        assert score == pytest.approx(expected)

    def test_legacy_score_clamps_to_upper_bound(self):
        score = ConfidenceScorer.compute(2.0, 2.0, 0.0)
        assert score == 1.0

    def test_legacy_score_clamps_to_lower_bound(self):
        score = ConfidenceScorer.compute(0.0, 0.5, 100.0)
        assert score == 0.0

    def test_score_uses_ml_scoring_when_enabled(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {
                "type": "xss",
                "source_tool": "nuclei",
                "evidence": {"type": "payload", "payload": "<script>"},
                "tool_agreement_level": 1.0,
                "cvss_score": 7.5,
            }
            score = scorer.score(
                finding, context={"is_public_endpoint": True, "requires_auth": False}
            )
            assert 0.0 <= score <= 1.0

    def test_extract_features_returns_all_keys(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {
                "type": "xss",
                "source_tool": "nuclei",
                "evidence": {"type": "payload", "payload": "<script>"},
                "tool_agreement_level": 1.0,
                "cvss_score": 7.5,
            }
            features = scorer._extract_features(
                finding, {"is_public_endpoint": True, "requires_auth": False}
            )
            assert set(features.keys()) == {
                "category_fp_rate",
                "tool_accuracy",
                "evidence_quality",
                "multi_tool_agreement",
                "context",
                "cvss_severity",
            }

    def test_extract_features_unknown_type_uses_default_fp(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {"type": "unknown_type", "source_tool": "unknown", "evidence": {}}
            features = scorer._extract_features(finding)
            assert features["category_fp_rate"] == 1.0 - 0.20  # default FP rate

    def test_extract_features_unknown_tool_uses_default_accuracy(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {"type": "xss", "source_tool": "unknown_tool_xyz", "evidence": {}}
            features = scorer._extract_features(finding)
            assert features["tool_accuracy"] == 0.50

    def test_extract_features_without_context_uses_defaults(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {"type": "xss", "source_tool": "nuclei", "evidence": {}}
            features = scorer._extract_features(finding)
            assert features["context"] == 0.9  # is_public=True by default

    def test_extract_features_authenticated_lowers_context_score(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {"type": "xss", "source_tool": "nuclei", "evidence": {}}
            features = scorer._extract_features(
                finding, {"is_public_endpoint": True, "requires_auth": True}
            )
            assert features["context"] == 0.7

    def test_extract_features_non_public_uses_0_8(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {"type": "xss", "source_tool": "nuclei", "evidence": {}}
            features = scorer._extract_features(
                finding, {"is_public_endpoint": False, "requires_auth": False}
            )
            assert features["context"] == 0.8

    def test_legacy_score_handles_string_agreement_level(self):
        scorer = ConfidenceScorer()
        finding = {
            "tool_agreement_level": "high",
            "evidence_strength": 0.8,
            "fp_likelihood": 0.1,
        }
        with patch("models.confidence_scorer.is_enabled", return_value=False):
            score = scorer.score(finding)
            assert 0.0 <= score <= 1.0

    def test_legacy_score_handles_missing_keys(self):
        scorer = ConfidenceScorer()
        finding = {"irrelevant": "data"}
        with patch("models.confidence_scorer.is_enabled", return_value=False):
            score = scorer.score(finding)
            expected = (0.7 * 0.7) / (1 + 0.2)
            assert score == pytest.approx(expected)

    def test_evidence_quality_minimal_for_non_dict_evidence(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {
                "type": "xss",
                "source_tool": "nuclei",
                "evidence": "string evidence",
            }
            features = scorer._extract_features(finding)
            assert features["evidence_quality"] == 0.6

    def test_evidence_quality_none_for_empty_evidence(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {"type": "xss", "source_tool": "nuclei", "evidence": {}}
            features = scorer._extract_features(finding)
            assert features["evidence_quality"] == 0.3

    def test_multi_tool_agreement_from_string(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {
                "type": "xss",
                "source_tool": "nuclei",
                "evidence": {},
                "tool_agreement_level": "high",
            }
            features = scorer._extract_features(finding)
            assert features["multi_tool_agreement"] == pytest.approx(1.0 * 0.33)

    def test_cvss_score_parsing(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {
                "type": "xss",
                "source_tool": "nuclei",
                "evidence": {},
                "cvss_score": 8.5,
            }
            features = scorer._extract_features(finding)
            assert features["cvss_severity"] == pytest.approx(0.85)

    def test_cvss_score_defaults_to_zero(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            finding = {"type": "xss", "source_tool": "nuclei", "evidence": {}}
            features = scorer._extract_features(finding)
            assert features["cvss_severity"] == 0.0

    def test_score_range_always_between_0_and_1(self):
        with patch("models.confidence_scorer.is_enabled", return_value=True):
            scorer = ConfidenceScorer()
            f1 = {
                "type": "xss",
                "source_tool": "nuclei",
                "evidence": {"type": "verified"},
                "tool_agreement_level": 1.0,
                "cvss_score": 10.0,
            }
            f2 = {
                "type": "xss",
                "source_tool": "unknown",
                "evidence": {},
                "tool_agreement_level": 0.0,
                "cvss_score": 0.0,
            }
            s1 = scorer.score(f1, {"is_public_endpoint": True, "requires_auth": False})
            s2 = scorer.score(f2, {"is_public_endpoint": False, "requires_auth": True})
            assert 0.0 <= s1 <= 1.0
            assert 0.0 <= s2 <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Feedback Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFindingFeedback:
    """Tests for FindingFeedback dataclass."""

    def test_init_sets_fields(self):
        fb = FindingFeedback(
            finding_id="f-001",
            engagement_id="eng-001",
            is_true_positive=True,
            analyst_notes="Confirmed SQL injection",
            corrected_severity="CRITICAL",
        )
        assert fb.finding_id == "f-001"
        assert fb.engagement_id == "eng-001"
        assert fb.is_true_positive is True
        assert fb.analyst_notes == "Confirmed SQL injection"
        assert fb.corrected_severity == "CRITICAL"

    def test_default_analyst_notes(self):
        fb = FindingFeedback(
            finding_id="f-001",
            engagement_id="eng-001",
            is_true_positive=False,
        )
        assert fb.analyst_notes == ""
        assert fb.corrected_severity is None


class TestFeedbackLearningLoop:
    """Tests for FeedbackLearningLoop."""

    FP_ALERT_THRESHOLD = 0.30

    @pytest.mark.requires_db
    def test_on_feedback_returns_none_when_feature_disabled(self):
        with patch("models.feedback.is_enabled", return_value=False):
            loop = FeedbackLearningLoop()
            fb = FindingFeedback("f-001", "eng-001", True)
            result = loop.on_feedback(fb)
            assert result is None

    @pytest.mark.requires_db
    def test_on_feedback_stores_feedback_when_enabled(self):
        with (
            patch("models.feedback.get_db"),
            patch("models.feedback.is_enabled", return_value=True),
            patch.object(FeedbackLearningLoop, "_store_feedback"),
            patch.object(FeedbackLearningLoop, "_update_finding"),
            patch.object(
                FeedbackLearningLoop, "_update_tool_accuracy", return_value=True
            ),
            patch.object(
                FeedbackLearningLoop, "_update_confidence_model", return_value=True
            ),
            patch.object(
                FeedbackLearningLoop, "_get_finding_source_tool", return_value="nuclei"
            ),
            patch.object(FeedbackLearningLoop, "_get_tool_fp_rate", return_value=0.1),
        ):
            loop = FeedbackLearningLoop()
            fb = FindingFeedback("f-001", "eng-001", True)
            result = loop.on_feedback(fb)
            assert result["feedback_stored"] is True
            assert result["finding_updated"] is True
            assert result["accuracy_adjusted"] is True
            assert result["weights_adjusted"] is True

    @pytest.mark.requires_db
    def test_on_feedback_sends_alert_when_fp_rate_exceeds_threshold(self):
        with (
            patch("models.feedback.get_db"),
            patch("models.feedback.is_enabled", return_value=True),
            patch.object(FeedbackLearningLoop, "_store_feedback"),
            patch.object(FeedbackLearningLoop, "_update_finding"),
            patch.object(
                FeedbackLearningLoop, "_update_tool_accuracy", return_value=True
            ),
            patch.object(
                FeedbackLearningLoop, "_update_confidence_model", return_value=True
            ),
            patch.object(
                FeedbackLearningLoop, "_get_finding_source_tool", return_value="nikto"
            ),
            patch.object(FeedbackLearningLoop, "_get_tool_fp_rate", return_value=0.50),
            patch.object(FeedbackLearningLoop, "_send_alert") as mock_alert,
        ):
            loop = FeedbackLearningLoop()
            fb = FindingFeedback("f-001", "eng-001", False)
            result = loop.on_feedback(fb)
            assert result["alert_sent"] is True
            mock_alert.assert_called_once_with("nikto", 0.50)

    @pytest.mark.requires_db
    def test_on_feedback_does_not_send_alert_when_fp_rate_below_threshold(self):
        with (
            patch("models.feedback.get_db"),
            patch("models.feedback.is_enabled", return_value=True),
            patch.object(FeedbackLearningLoop, "_store_feedback"),
            patch.object(FeedbackLearningLoop, "_update_finding"),
            patch.object(
                FeedbackLearningLoop, "_update_tool_accuracy", return_value=True
            ),
            patch.object(
                FeedbackLearningLoop, "_update_confidence_model", return_value=True
            ),
            patch.object(
                FeedbackLearningLoop, "_get_finding_source_tool", return_value="nuclei"
            ),
            patch.object(FeedbackLearningLoop, "_get_tool_fp_rate", return_value=0.10),
        ):
            loop = FeedbackLearningLoop()
            fb = FindingFeedback("f-001", "eng-001", True)
            result = loop.on_feedback(fb)
            assert "alert_sent" not in result

    @pytest.mark.requires_db
    def test_on_feedback_skips_alert_when_no_source_tool(self):
        with (
            patch("models.feedback.get_db"),
            patch("models.feedback.is_enabled", return_value=True),
            patch.object(FeedbackLearningLoop, "_store_feedback"),
            patch.object(FeedbackLearningLoop, "_update_finding"),
            patch.object(
                FeedbackLearningLoop, "_update_tool_accuracy", return_value=True
            ),
            patch.object(
                FeedbackLearningLoop, "_update_confidence_model", return_value=True
            ),
            patch.object(
                FeedbackLearningLoop, "_get_finding_source_tool", return_value=None
            ),
        ):
            loop = FeedbackLearningLoop()
            fb = FindingFeedback("f-001", "eng-001", True)
            result = loop.on_feedback(fb)
            assert "alert_sent" not in result

    @pytest.mark.requires_db
    def test_update_tool_accuracy_returns_false_without_source_tool(self):
        loop = FeedbackLearningLoop()
        with patch.object(loop, "_get_finding_source_tool", return_value=None):
            fb = FindingFeedback("f-001", "eng-001", True)
            assert loop._update_tool_accuracy(fb) is False

    @pytest.mark.requires_db
    def test_update_tool_accuracy_returns_false_without_org_id(self):
        loop = FeedbackLearningLoop()
        with (
            patch.object(loop, "_get_finding_source_tool", return_value="nuclei"),
            patch.object(loop, "_get_finding_org_id", return_value=None),
        ):
            fb = FindingFeedback("f-001", "eng-001", True)
            assert loop._update_tool_accuracy(fb) is False

    @pytest.mark.requires_db
    def test_update_tool_accuracy_records_verdict(self):
        mock_repo = MagicMock()
        mock_repo.record_verdict.return_value = True
        loop = FeedbackLearningLoop()
        loop._accuracy_repo = mock_repo
        with (
            patch.object(loop, "_get_finding_source_tool", return_value="nuclei"),
            patch.object(loop, "_get_finding_org_id", return_value="org-001"),
        ):
            fb = FindingFeedback("f-001", "eng-001", True)
            assert loop._update_tool_accuracy(fb) is True
            mock_repo.record_verdict.assert_called_once_with(
                org_id="org-001",
                source_tool="nuclei",
                is_true_positive=True,
            )

    @pytest.mark.requires_db
    def test_update_confidence_model_returns_false_without_source_tool(self):
        loop = FeedbackLearningLoop()
        with patch.object(loop, "_get_finding_source_tool", return_value=None):
            fb = FindingFeedback("f-001", "eng-001", True)
            assert loop._update_confidence_model(fb) is False

    @pytest.mark.requires_db
    def test_update_confidence_model_returns_true(self):
        loop = FeedbackLearningLoop()
        with (
            patch.object(loop, "_get_finding_source_tool", return_value="nuclei"),
            patch.object(loop, "_get_tool_fp_rate", return_value=0.1),
        ):
            fb = FindingFeedback("f-001", "eng-001", True)
            assert loop._update_confidence_model(fb) is True

    @pytest.mark.requires_db
    def test_fp_alert_threshold_class_constant(self):
        assert FeedbackLearningLoop.FP_ALERT_THRESHOLD == 0.30
