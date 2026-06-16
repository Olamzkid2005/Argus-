import json
from unittest.mock import MagicMock, patch

import pytest

from database.repositories.report_repository import ReportRepository


@pytest.fixture(autouse=True)
def mock_db_cursor():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [
        ("id",), ("engagement_id",), ("generated_by",), ("executive_summary",),
        ("full_report_json",), ("sbom_json",), ("risk_level",),
        ("total_findings",), ("critical_count",), ("high_count",),
        ("medium_count",), ("low_count",), ("model_used",), ("created_at",),
    ]

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cursor
    mock_cm.__exit__.return_value = None

    with patch("database.repositories.report_repository.db_cursor", return_value=mock_cm):
        yield mock_cursor


class TestReportRepositoryInit:
    def test_uses_env_var_fallback(self):
        with patch.dict("os.environ", {"DATABASE_URL": "postgres://env:5432/db"}, clear=True):
            repo = ReportRepository()
            assert repo.db_conn == "postgres://env:5432/db"

    def test_uses_passed_db_conn(self):
        with patch.dict("os.environ", {"DATABASE_URL": "postgres://env:5432/db"}, clear=True):
            repo = ReportRepository(db_conn="postgres://passed:5432/db")
            assert repo.db_conn == "postgres://passed:5432/db"


class TestUpsertReport:
    def test_inserts_with_correct_severity_counts(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = ("report-1",)
        repo = ReportRepository()

        result = repo.upsert_report(
            engagement_id="eng-1",
            report_data={
                "executive_summary": "Summary",
                "risk_level": "high",
                "detailed_findings": [
                    {"severity": "CRITICAL"},
                    {"severity": "HIGH"},
                    {"severity": "MEDIUM"},
                    {"severity": "LOW"},
                    {"severity": "critical"},
                    {"severity": "high"},
                ],
            },
        )

        assert result == "report-1"
        mock_db_cursor.execute.assert_called_once()
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "INSERT INTO reports" in sql
        assert params[5] == 6  # total_findings
        assert params[6] == 2  # critical_count
        assert params[7] == 2  # high_count
        assert params[8] == 1  # medium_count
        assert params[9] == 1  # low_count

    def test_handles_empty_findings_gracefully(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = ("report-2",)
        repo = ReportRepository()

        result = repo.upsert_report(
            engagement_id="eng-1",
            report_data={"executive_summary": "Summary", "risk_level": "low"},
        )

        assert result == "report-2"
        sql, params = mock_db_cursor.execute.call_args[0]
        assert params[5] == 0  # total_findings
        assert params[6] == 0  # critical_count
        assert params[7] == 0  # high_count
        assert params[8] == 0  # medium_count
        assert params[9] == 0  # low_count

    def test_handles_findings_key_fallback(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = ("report-3",)
        repo = ReportRepository()

        result = repo.upsert_report(
            engagement_id="eng-1",
            report_data={
                "executive_summary": "Summary",
                "risk_level": "medium",
                "findings": [{"severity": "HIGH"}, {"severity": "LOW"}],
            },
        )

        assert result == "report-3"
        sql, params = mock_db_cursor.execute.call_args[0]
        assert params[5] == 2

    def test_returns_none_on_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = ReportRepository()

        result = repo.upsert_report(
            engagement_id="eng-1",
            report_data={"executive_summary": "Summary"},
        )

        assert result is None

    def test_returns_none_when_fetchone_returns_none(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = None
        repo = ReportRepository()

        result = repo.upsert_report(
            engagement_id="eng-1",
            report_data={"executive_summary": "Summary"},
        )

        assert result is None

    def test_includes_sbom_json_when_present(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = ("report-4",)
        repo = ReportRepository()

        result = repo.upsert_report(
            engagement_id="eng-1",
            report_data={"executive_summary": "Summary"},
            sbom_json={"bom": "data"},
        )

        assert result == "report-4"
        sql, params = mock_db_cursor.execute.call_args[0]
        assert params[11] == json.dumps({"bom": "data"})


class TestGetReport:
    def test_returns_report_dict_with_json_loaded_fields(self, mock_db_cursor):
        full_report = {"executive_summary": "Summary", "risk_level": "high"}
        mock_db_cursor.fetchone.return_value = (
            "1", "eng-1", "llm", "Summary", json.dumps(full_report), None,
            "high", 5, 1, 2, 1, 1, "gpt-4", "2025-01-01",
        )
        repo = ReportRepository()

        result = repo.get_report("eng-1")

        assert result["id"] == "1"
        assert result["full_report_json"] == full_report
        assert result["risk_level"] == "high"
        mock_db_cursor.execute.assert_called_once()

    def test_returns_none_when_not_found(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = None
        repo = ReportRepository()

        result = repo.get_report("eng-1")

        assert result is None

    def test_returns_none_on_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = ReportRepository()

        result = repo.get_report("eng-1")

        assert result is None


class TestDeleteReport:
    def test_returns_true_when_deleted(self, mock_db_cursor):
        mock_db_cursor.rowcount = 1
        repo = ReportRepository()

        result = repo.delete_report("eng-1")

        assert result is True
        mock_db_cursor.execute.assert_called_once()
        assert "DELETE FROM reports" in mock_db_cursor.execute.call_args[0][0]

    def test_returns_false_when_no_rows_affected(self, mock_db_cursor):
        mock_db_cursor.rowcount = 0
        repo = ReportRepository()

        result = repo.delete_report("eng-1")

        assert result is False

    def test_returns_false_on_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = ReportRepository()

        result = repo.delete_report("eng-1")

        assert result is False
