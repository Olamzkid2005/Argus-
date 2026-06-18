from unittest.mock import MagicMock, patch

import pytest

from database.repositories.tool_accuracy_repository import ToolAccuracyRepository


@pytest.fixture(autouse=True)
def mock_db_cursor():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [
        ("org_id",),
        ("source_tool",),
        ("fp_rate",),
    ]

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cursor
    mock_cm.__exit__.return_value = None

    with patch(
        "database.repositories.tool_accuracy_repository.db_cursor", return_value=mock_cm
    ):
        yield mock_cursor


class TestRecordVerdict:
    def test_returns_false_with_empty_org_id(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.record_verdict(
            org_id="", source_tool="nuclei", is_true_positive=True
        )

        assert result is False
        mock_db_cursor.execute.assert_not_called()

    def test_returns_false_with_empty_source_tool(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.record_verdict(
            org_id="org-1", source_tool="", is_true_positive=True
        )

        assert result is False
        mock_db_cursor.execute.assert_not_called()

    def test_inserts_and_returns_true(self, mock_db_cursor):
        mock_db_cursor.rowcount = 1
        repo = ToolAccuracyRepository()

        result = repo.record_verdict(
            org_id="org-1", source_tool="nuclei", is_true_positive=True
        )

        assert result is True
        mock_db_cursor.execute.assert_called_once()
        sql = mock_db_cursor.execute.call_args[0][0]
        assert "INSERT INTO tool_accuracy" in sql
        assert "ON CONFLICT" in sql

    def test_handles_false_positive_verdict(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.record_verdict(
            org_id="org-1", source_tool="nuclei", is_true_positive=False
        )

        assert result is True
        sql, params = mock_db_cursor.execute.call_args[0]
        assert params[0] == "org-1"
        assert params[1] == "nuclei"
        assert params[2] is False
        assert params[3] is False
        assert params[4] is False

    def test_returns_false_on_db_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = ToolAccuracyRepository()

        result = repo.record_verdict(
            org_id="org-1", source_tool="nuclei", is_true_positive=True
        )

        assert result is False


class TestLoadFpRates:
    def test_returns_dict_of_tool_to_fp_rate(self, mock_db_cursor):
        mock_db_cursor.fetchall.return_value = [
            ("nuclei", 0.15),
            ("sqlmap", 0.05),
        ]
        repo = ToolAccuracyRepository()

        result = repo.load_fp_rates(org_id="org-1")

        assert result == {"nuclei": 0.15, "sqlmap": 0.05}
        mock_db_cursor.execute.assert_called_once()

    def test_returns_empty_dict_for_empty_org_id(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.load_fp_rates(org_id="")

        assert result == {}
        mock_db_cursor.execute.assert_not_called()

    def test_returns_empty_dict_on_db_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = ToolAccuracyRepository()

        result = repo.load_fp_rates(org_id="org-1")

        assert result == {}

    def test_returns_empty_dict_when_no_rows(self, mock_db_cursor):
        mock_db_cursor.fetchall.return_value = []
        repo = ToolAccuracyRepository()

        result = repo.load_fp_rates(org_id="org-1")

        assert result == {}


class TestGetToolFpRate:
    def test_returns_rate_for_known_tool(self, mock_db_cursor):
        mock_db_cursor.fetchall.return_value = [
            ("nuclei", 0.15),
            ("sqlmap", 0.05),
        ]
        repo = ToolAccuracyRepository()

        result = repo.get_tool_fp_rate(org_id="org-1", source_tool="nuclei")

        assert result == 0.15

    def test_returns_none_for_unknown_tool(self, mock_db_cursor):
        mock_db_cursor.fetchall.return_value = [
            ("nuclei", 0.15),
        ]
        repo = ToolAccuracyRepository()

        result = repo.get_tool_fp_rate(org_id="org-1", source_tool="sqlmap")

        assert result is None

    def test_returns_none_for_empty_org_id(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.get_tool_fp_rate(org_id="", source_tool="nuclei")

        assert result is None
