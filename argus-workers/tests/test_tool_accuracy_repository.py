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


class TestSaveFpRates:
    def test_returns_false_with_empty_org_id(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.save_fp_rates(org_id="", tool_fp_rates={"nuclei": 0.15})

        assert result is False
        mock_db_cursor.execute.assert_not_called()

    def test_returns_false_with_empty_rates(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.save_fp_rates(org_id="org-1", tool_fp_rates={})

        assert result is False
        mock_db_cursor.execute.assert_not_called()

    def test_inserts_new_rows_for_multiple_tools(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.save_fp_rates(
            org_id="org-1",
            tool_fp_rates={"nuclei": 0.15, "sqlmap": 0.05, "gau": 0.75},
        )

        assert result is True
        assert mock_db_cursor.execute.call_count == 3
        sql, params = mock_db_cursor.execute.call_args_list[0][0]
        assert "INSERT INTO tool_accuracy" in sql
        assert "ON CONFLICT" in sql
        assert params[0] == "org-1"
        assert params[1] == "nuclei"
        # params: [org_id, source_tool, fp_rate_insert, fp_rate_update]
        assert params[2] == 0.15

    def test_clamps_fp_rate_out_of_range(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.save_fp_rates(
            org_id="org-1",
            tool_fp_rates={"nuclei": 1.5, "sqlmap": -0.5},
        )

        assert result is True
        assert mock_db_cursor.execute.call_count == 2
        # nuclei clamped to 1.0 — fp_rate at param index 2
        _, params = mock_db_cursor.execute.call_args_list[0][0]
        assert params[2] == 1.0
        # sqlmap clamped to 0.0
        _, params2 = mock_db_cursor.execute.call_args_list[1][0]
        assert params2[2] == 0.0

    def test_skips_empty_tool_name(self, mock_db_cursor):
        repo = ToolAccuracyRepository()

        result = repo.save_fp_rates(
            org_id="org-1",
            tool_fp_rates={"": 0.1, "nuclei": 0.2},
        )

        assert result is True
        assert mock_db_cursor.execute.call_count == 1
        _, params = mock_db_cursor.execute.call_args_list[0][0]
        assert params[1] == "nuclei"

    def test_returns_false_on_db_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = ToolAccuracyRepository()

        result = repo.save_fp_rates(
            org_id="org-1",
            tool_fp_rates={"nuclei": 0.15},
        )

        assert result is False

    def test_insert_has_zero_verdict_counters_in_sql(self, mock_db_cursor):
        """Verify the SQL string contains literal 0s for verdict counters.

        The verdict counters (total_verdicts=0, true_positives=0, false_positives=0)
        are SQL literals in the INSERT, not Python params. Parse the SQL to verify.
        """
        repo = ToolAccuracyRepository()

        repo.save_fp_rates(org_id="org-1", tool_fp_rates={"nuclei": 0.15})

        sql, _ = mock_db_cursor.execute.call_args[0]
        # The column values section should have: 0, 0, 0, %s
        # Extract the VALUES(...) portion
        import re
        values_match = re.search(r"VALUES\s*\((.*?)\)", sql, re.IGNORECASE | re.DOTALL)
        assert values_match is not None, "No VALUES found in SQL"
        values_clause = values_match.group(1)
        # Should contain the three 0 literals before the fp_rate %s
        values_compact = values_clause.replace(" ", "").replace("\n", "")
        assert "0,0,0" in values_compact
