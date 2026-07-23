"""Tests for tasks.posture — Compliance posture scoring Celery tasks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tasks.posture import _check_compliance_alerts
from tasks.posture import recompute_posture as _recompute_posture_task

# Call the original unwrapped function to avoid Celery auto-retry wrapper
recompute_posture = _recompute_posture_task._orig_run


class FakePostureSnapshot:
    def __init__(self, composite_score, trend="stable"):
        self.composite_score = composite_score
        self.trend = trend


class TestRecomputePosture:
    """Tests for recompute_posture()."""

    @patch("database.repositories.finding_repository.FindingRepository")
    @patch("compliance_posture_scorer.CompliancePostureScorer")
    @patch("database.connection.db_cursor")
    def test_resolves_org_id_from_db_if_not_provided(
        self, mock_db_cursor, mock_scorer_cls, mock_repo_cls
    ):
        mock_cm = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("org-42",)
        mock_cm.__enter__.return_value = mock_cursor
        mock_db_cursor.return_value = mock_cm

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        mock_repo.get_findings_by_engagement.return_value = ([{"id": "f1"}], 1)

        mock_scorer = MagicMock()
        mock_scorer_cls.return_value = mock_scorer
        mock_snapshot = MagicMock()
        mock_snapshot.composite_score = 85.0
        mock_snapshot.trend = "improving"
        mock_scorer.compute_and_save.return_value = mock_snapshot

        recompute_posture("eng-001", org_id=None)

        mock_cursor.execute.assert_called_once_with(
            "SELECT org_id FROM engagements WHERE id = %s",
            ("eng-001",),
        )
        mock_scorer.compute_and_save.assert_called_once()
        _, kwargs = mock_scorer.compute_and_save.call_args
        assert kwargs["org_id"] == "org-42"

    @patch("database.repositories.finding_repository.FindingRepository")
    @patch("compliance_posture_scorer.CompliancePostureScorer")
    @patch("database.connection.db_cursor")
    def test_loads_findings_and_computes_posture(
        self, mock_db_cursor, mock_scorer_cls, mock_repo_cls
    ):
        mock_cm = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("org-42",)
        mock_cm.__enter__.return_value = mock_cursor
        mock_db_cursor.return_value = mock_cm

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        mock_repo.get_findings_by_engagement.return_value = (
            [{"id": "f1", "type": "SQL_INJECTION"}],
            1,
        )

        mock_scorer = MagicMock()
        mock_scorer_cls.return_value = mock_scorer
        mock_snapshot = MagicMock()
        mock_snapshot.composite_score = 72.5
        mock_snapshot.trend = "declining"
        mock_scorer.compute_and_save.return_value = mock_snapshot

        result = recompute_posture("eng-001", org_id="org-42")

        mock_repo.get_findings_by_engagement.assert_called_once_with(
            "eng-001", limit=100000
        )
        assert result["composite_score"] == 72.5
        assert result["trend"] == "declining"
        assert result["findings_count"] == 1

    @patch("tasks.posture._check_compliance_alerts")
    @patch("database.repositories.finding_repository.FindingRepository")
    @patch("compliance_posture_scorer.CompliancePostureScorer")
    @patch("database.connection.db_cursor")
    def test_with_no_findings_returns_score_100(
        self, mock_db_cursor, mock_scorer_cls, mock_repo_cls, mock_check_alerts
    ):
        mock_cm = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("org-42",)
        mock_cm.__enter__.return_value = mock_cursor
        mock_db_cursor.return_value = mock_cm

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        mock_repo.get_findings_by_engagement.return_value = ([], 0)

        mock_scorer = MagicMock()
        mock_scorer_cls.return_value = mock_scorer
        mock_snapshot = MagicMock()
        mock_snapshot.composite_score = 100.0
        mock_snapshot.trend = "stable"
        mock_scorer.compute_and_save.return_value = mock_snapshot

        result = recompute_posture("eng-001", org_id="org-42")

        assert result["composite_score"] == 100.0
        assert result["findings_count"] == 0
        mock_scorer.compute_and_save.assert_called_once_with([], org_id="org-42")

    @patch("database.repositories.finding_repository.FindingRepository")
    @patch("database.connection.db_cursor")
    def test_handles_errors_with_retry(self, mock_db_cursor, mock_repo_cls):
        mock_cm = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("org-42",)
        mock_cm.__enter__.return_value = mock_cursor
        mock_db_cursor.return_value = mock_cm

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        mock_repo.get_findings_by_engagement.side_effect = Exception("Query failed")

        # Patch retry on the bound task self
        from tasks.posture import recompute_posture as _task

        bound_self = _task._orig_run.__self__
        orig_retry = bound_self.retry
        bound_self.retry = MagicMock(side_effect=Exception("Retry triggered"))

        try:
            with pytest.raises(Exception, match="Retry triggered"):
                recompute_posture("eng-001", org_id="org-42")
        finally:
            bound_self.retry = orig_retry


class TestCheckComplianceAlerts:
    """Tests for _check_compliance_alerts()."""

    @patch("streaming.emit_error")
    def test_emits_critical_alert_for_score_below_30(self, mock_emit_error):
        snapshot = FakePostureSnapshot(composite_score=25.0, trend="declining")

        _check_compliance_alerts("eng-001", snapshot, "org-42")

        mock_emit_error.assert_called_once()
        _, kwargs = mock_emit_error.call_args
        assert "CRITICAL" in kwargs["error"]
        assert kwargs["engagement_id"] == "eng-001"
        assert kwargs["phase"] == "posture"

    @patch("streaming.emit_error")
    def test_emits_warning_alert_for_score_below_50(self, mock_emit_error):
        snapshot = FakePostureSnapshot(composite_score=40.0, trend="stable")

        _check_compliance_alerts("eng-001", snapshot, "org-42")

        mock_emit_error.assert_called_once()
        _, kwargs = mock_emit_error.call_args
        assert "WARNING" in kwargs["error"]

    @patch("streaming.emit_error")
    def test_emits_info_alert_for_score_below_70(self, mock_emit_error):
        snapshot = FakePostureSnapshot(composite_score=60.0, trend="improving")

        _check_compliance_alerts("eng-001", snapshot, "org-42")

        mock_emit_error.assert_called_once()
        _, kwargs = mock_emit_error.call_args
        assert "INFO" in kwargs["error"]

    @patch("streaming.emit_error")
    def test_does_nothing_for_score_above_70(self, mock_emit_error):
        snapshot = FakePostureSnapshot(composite_score=85.0, trend="stable")

        _check_compliance_alerts("eng-001", snapshot, "org-42")

        mock_emit_error.assert_not_called()
