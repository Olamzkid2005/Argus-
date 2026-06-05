from unittest.mock import MagicMock, patch

import pytest

from database.repositories.agent_decision_repository import AgentDecisionRepository


@pytest.fixture(autouse=True)
def mock_db_cursor():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [
        ("id",), ("engagement_id",), ("phase",), ("iteration",),
        ("tool_selected",), ("arguments",), ("reasoning",),
        ("was_fallback",), ("input_tokens",), ("output_tokens",),
        ("cost_usd",), ("created_at",),
    ]

    def _set_description(sql, params=None):
        if "SUM" in sql or "total_decisions" in sql:
            mock_cursor.description = [
                ("total_decisions",), ("total_cost_usd",),
                ("fallback_count",), ("llm_count",),
            ]
        else:
            mock_cursor.description = [
                ("id",), ("engagement_id",), ("phase",), ("iteration",),
                ("tool_selected",), ("arguments",), ("reasoning",),
                ("was_fallback",), ("input_tokens",), ("output_tokens",),
                ("cost_usd",), ("created_at",),
            ]

    mock_cursor.execute.side_effect = _set_description

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cursor
    mock_cm.__exit__.return_value = None

    with patch("database.repositories.agent_decision_repository.db_cursor", return_value=mock_cm):
        yield mock_cursor


class TestAgentDecisionRepositoryInit:
    def test_uses_env_var_when_no_db_conn_passed(self):
        with patch.dict("os.environ", {"DATABASE_URL": "postgres://env:5432/db"}, clear=True):
            repo = AgentDecisionRepository()
            assert repo.db_conn == "postgres://env:5432/db"

    def test_uses_passed_db_conn_over_env_var(self):
        with patch.dict("os.environ", {"DATABASE_URL": "postgres://env:5432/db"}, clear=True):
            repo = AgentDecisionRepository(db_conn="postgres://passed:5432/db")
            assert repo.db_conn == "postgres://passed:5432/db"


class TestLogDecision:
    def test_inserts_and_returns_id(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = ("decision-1",)
        repo = AgentDecisionRepository()

        result = repo.log_decision(
            engagement_id="eng-1",
            phase="scan",
            iteration=1,
            tool_selected="nuclei",
            arguments={"target": "example.com"},
            reasoning="best tool",
            was_fallback=False,
            input_tokens=100,
            output_tokens=50,
        )

        assert result == "decision-1"
        mock_db_cursor.execute.assert_called_once()
        sql = mock_db_cursor.execute.call_args[0][0]
        assert "INSERT INTO agent_decisions" in sql
        assert "RETURNING id" in sql

    def test_returns_none_on_db_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = AgentDecisionRepository()

        result = repo.log_decision(
            engagement_id="eng-1",
            phase="scan",
            iteration=1,
            tool_selected="nuclei",
            arguments={},
        )

        assert result is None

    def test_returns_none_when_fetchone_returns_none(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = None
        repo = AgentDecisionRepository()

        result = repo.log_decision(
            engagement_id="eng-1",
            phase="scan",
            iteration=1,
            tool_selected="nuclei",
            arguments={},
        )

        assert result is None


class TestGetDecisions:
    def test_returns_list_of_dicts(self, mock_db_cursor):
        mock_db_cursor.fetchall.return_value = [
            ("1", "eng-1", "scan", 1, "nuclei", "{}", "", False, 100, 50, 0.015, "2025-01-01"),
        ]
        repo = AgentDecisionRepository()

        result = repo.get_decisions("eng-1")

        assert len(result) == 1
        assert result[0]["id"] == "1"
        assert result[0]["tool_selected"] == "nuclei"
        mock_db_cursor.execute.assert_called_once()
        assert "WHERE engagement_id = %s" in mock_db_cursor.execute.call_args[0][0]

    def test_returns_empty_list_on_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = AgentDecisionRepository()

        result = repo.get_decisions("eng-1")

        assert result == []

    def test_returns_empty_list_when_no_results(self, mock_db_cursor):
        mock_db_cursor.fetchall.return_value = []
        repo = AgentDecisionRepository()

        result = repo.get_decisions("eng-1")

        assert result == []


class TestGetTotalCost:
    def test_returns_sum(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = (1.5,)
        repo = AgentDecisionRepository()

        result = repo.get_total_cost("eng-1")

        assert result == 1.5

    def test_returns_0_on_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = AgentDecisionRepository()

        result = repo.get_total_cost("eng-1")

        assert result == 0.0

    def test_returns_0_when_fetchone_returns_none(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = None
        repo = AgentDecisionRepository()

        result = repo.get_total_cost("eng-1")

        assert result == 0.0


class TestGetStatsSince:
    def test_returns_stats_dict(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = (10, 2.5, 3, 7)
        repo = AgentDecisionRepository()

        result = repo.get_stats_since(since_hours=24)

        assert result["total_decisions"] == 10
        assert result["total_cost_usd"] == 2.5
        assert result["fallback_count"] == 3
        assert result["llm_count"] == 7

    def test_returns_zeros_on_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = AgentDecisionRepository()

        result = repo.get_stats_since(since_hours=24)

        assert result == {"total_decisions": 0, "total_cost_usd": 0.0, "fallback_count": 0, "llm_count": 0}

    def test_returns_zeros_when_fetchone_returns_none(self, mock_db_cursor):
        mock_db_cursor.fetchone.return_value = None
        repo = AgentDecisionRepository()

        result = repo.get_stats_since(since_hours=24)

        assert result == {"total_decisions": 0, "total_cost_usd": 0.0, "fallback_count": 0, "llm_count": 0}


class TestGetRecentDecisions:
    def test_returns_list(self, mock_db_cursor):
        mock_db_cursor.fetchall.return_value = [
            ("1", "eng-1", "scan", 1, "nuclei", "{}", "", False, 100, 50, 0.015, "2025-01-01"),
        ]
        repo = AgentDecisionRepository()

        result = repo.get_recent_decisions(limit=5)

        assert len(result) == 1
        assert result[0]["tool_selected"] == "nuclei"
        assert "LIMIT %s" in mock_db_cursor.execute.call_args[0][0]

    def test_returns_empty_on_failure(self, mock_db_cursor):
        mock_db_cursor.execute.side_effect = Exception("DB error")
        repo = AgentDecisionRepository()

        result = repo.get_recent_decisions(limit=5)

        assert result == []

    def test_uses_default_limit(self, mock_db_cursor):
        mock_db_cursor.fetchall.return_value = []
        repo = AgentDecisionRepository()

        repo.get_recent_decisions()

        assert mock_db_cursor.execute.call_args[0][1][0] == 10


class TestEstimateCost:
    def test_with_no_tokens_returns_zero(self):
        repo = AgentDecisionRepository()

        result = repo._estimate_cost(None, None)

        assert result == 0.0

    def test_with_input_tokens_only(self):
        repo = AgentDecisionRepository()

        result = repo._estimate_cost(1000, None)

        assert result == 0.000150  # 1000/1000 * 0.000150

    def test_with_output_tokens_only(self):
        repo = AgentDecisionRepository()

        result = repo._estimate_cost(None, 1000)

        assert result == 0.000600  # 1000/1000 * 0.000600

    def test_calculates_correctly_with_both(self):
        repo = AgentDecisionRepository()

        result = repo._estimate_cost(2000, 500)

        expected = (2000 / 1000 * 0.000150) + (500 / 1000 * 0.000600)
        assert result == expected
