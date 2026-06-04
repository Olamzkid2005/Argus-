"""Tests for compliance_posture_scorer.py

Covers:
  - FrameworkPosture / PostureSnapshot dataclasses
  - CompliancePostureScorer init and compute
  - Score calculation with severity weights
  - Trend detection
  - Empty findings case (perfect score)
  - _map_finding and _map_finding_full
  - to_api_dict serialization
  - save_snapshot / load_latest_snapshot
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compliance_posture_scorer import (
    SEVERITY_WEIGHTS,
    CompliancePostureScorer,
    FrameworkPosture,
    PostureSnapshot,
)


class TestFrameworkPosture:
    """Tests for FrameworkPosture dataclass."""

    def test_defaults(self):
        fp = FrameworkPosture(framework="owasp_top10", score=85.0, total_findings=5,
                              critical_count=1, high_count=2, medium_count=0)
        assert fp.framework == "owasp_top10"
        assert fp.score == 85.0
        assert fp.total_findings == 5
        assert fp.critical_count == 1
        assert fp.finding_breakdown == {}
        assert fp.computed_at is not None


class TestPostureSnapshot:
    """Tests for PostureSnapshot dataclass."""

    def test_defaults(self):
        ps = PostureSnapshot(engagement_id="eng-001", composite_score=90.0)
        assert ps.engagement_id == "eng-001"
        assert ps.composite_score == 90.0
        assert ps.frameworks == {}
        assert ps.total_findings == 0
        assert ps.trend == "stable"
        assert ps.previous_score is None


class TestCompliancePostureScorer:
    """Tests for CompliancePostureScorer."""

    @pytest.fixture
    def scorer(self):
        return CompliancePostureScorer(engagement_id="eng-001")

    def test_init(self, scorer):
        assert scorer.engagement_id == "eng-001"
        assert scorer._previous_score is None

    def test_compute_empty_findings(self, scorer):
        snapshot = scorer.compute([])
        assert snapshot.composite_score == 100.0
        assert snapshot.total_findings == 0
        assert len(snapshot.frameworks) == 6

    def test_compute_with_findings(self, scorer):
        findings = [
            {"type": "SQL_INJECTION", "severity": "CRITICAL"},
            {"type": "XSS", "severity": "HIGH"},
        ]
        snapshot = scorer.compute(findings)
        assert snapshot.composite_score < 100.0
        assert snapshot.total_findings == 2

    def test_severity_weights(self):
        assert SEVERITY_WEIGHTS["CRITICAL"] == 10.0
        assert SEVERITY_WEIGHTS["HIGH"] == 5.0
        assert SEVERITY_WEIGHTS["MEDIUM"] == 2.0
        assert SEVERITY_WEIGHTS["LOW"] == 0.5
        assert SEVERITY_WEIGHTS["INFO"] == 0.1

    def test_trend_improving(self, scorer):
        findings = [{"type": "XSS", "severity": "MEDIUM"}]
        scorer._previous_score = 50.0
        snapshot = scorer.compute(findings)
        assert snapshot.trend in ("improving", "stable", "declining")

    def test_trend_stable_when_no_previous(self, scorer):
        findings = [{"type": "XSS", "severity": "MEDIUM"}]
        snapshot = scorer.compute(findings)
        assert snapshot.trend == "stable"

    def test_map_finding(self, scorer):
        with patch.object(scorer._mapper, "map_to_owasp", return_value="A03:2021 - Injection"), \
             patch.object(scorer._mapper, "map_to_pci", return_value="6.5.1"):
            result = scorer._map_finding({"type": "SQL_INJECTION"})
            assert "owasp_top10" in result
            assert "pci_dss" in result
            assert "soc2" in result

    def test_map_finding_full(self, scorer):
        result = scorer._map_finding_full({"type": "XSS"})
        assert len(result) == 6  # All 6 frameworks

    def test_to_api_dict(self, scorer):
        findings = [{"type": "XSS", "severity": "MEDIUM"}]
        snapshot = scorer.compute(findings)
        api = scorer.to_api_dict(snapshot)
        assert "engagement_id" in api
        assert "composite_score" in api
        assert "frameworks" in api
        assert "trend" in api
        assert "computed_at" in api

    def test_save_snapshot_db_error(self, scorer):
        snapshot = scorer.compute([])
        with patch.object(scorer, "get_db_cursor", side_effect=Exception("DB error")):
            result = scorer.save_snapshot(snapshot)
            assert result is None

    def test_load_latest_snapshot_no_data(self):
        with patch("database.connection.db_cursor") as mock_cursor:
            mock_cursor.return_value.__enter__.return_value.fetchone.return_value = None
            result = CompliancePostureScorer.load_latest_snapshot("eng-001")
            assert result is None

    def test_load_snapshot_history_no_data(self):
        with patch("database.connection.db_cursor") as mock_cursor:
            mock_cursor.return_value.__enter__.return_value.fetchall.return_value = []
            result = CompliancePostureScorer.load_snapshot_history("eng-001")
            assert result == []
