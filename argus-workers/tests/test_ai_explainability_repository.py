import json
from unittest.mock import MagicMock, patch

import pytest

from database.repositories.ai_explainability_repository import (
    AIExplainabilityRepository,
)


@pytest.fixture(autouse=True)
def mock_db():
    mock_cursor = MagicMock()
    mock_cursor.description = [
        ("id",), ("cluster_id",), ("explanation",),
        ("model_version",), ("token_count",), ("created_at",),
    ]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_db_instance = MagicMock()
    mock_db_instance.get_connection.return_value = mock_conn

    with patch(
        "database.repositories.ai_explainability_repository.get_db",
        return_value=mock_db_instance,
    ):
        yield mock_cursor


class TestAIExplainabilityRepositoryInit:
    def test_logs_warning_when_db_connection_passed(self, caplog):
        caplog.set_level("WARNING")
        passed_conn = MagicMock()

        AIExplainabilityRepository(db_connection=passed_conn)

        assert any("received a shared connection" in msg for msg in caplog.messages)

    def test_uses_pool_when_no_db_connection_passed(self):
        repo = AIExplainabilityRepository()

        assert repo._db is None


class TestCreateExplanation:
    def test_inserts_and_returns_dict(self, mock_db):
        mock_db.fetchone.return_value = (1, "cluster-1", "explanation text", "gpt-4", 150, "2025-01-01")

        repo = AIExplainabilityRepository()
        result = repo.create_explanation(
            cluster_id="cluster-1",
            explanation="explanation text",
            model_version="gpt-4",
            token_count=150,
        )

        assert result["id"] == 1
        assert result["cluster_id"] == "cluster-1"
        assert result["explanation"] == "explanation text"
        assert result["model_version"] == "gpt-4"
        assert result["token_count"] == 150
        mock_db.execute.assert_called_once()
        assert "INSERT INTO ai_explanations" in mock_db.execute.call_args[0][0]

    def test_raises_on_failure(self, mock_db):
        mock_db.execute.side_effect = Exception("DB error")

        repo = AIExplainabilityRepository()
        with pytest.raises(Exception, match="DB error"):
            repo.create_explanation(
                cluster_id="cluster-1",
                explanation="text",
                model_version="gpt-4",
                token_count=150,
            )

    def test_returns_none_when_fetchone_returns_none(self, mock_db):
        mock_db.fetchone.return_value = None

        repo = AIExplainabilityRepository()
        result = repo.create_explanation(
            cluster_id="cluster-1",
            explanation="text",
            model_version="gpt-4",
            token_count=150,
        )

        assert result is None


class TestCreateTrace:
    def test_inserts_and_returns_dict(self, mock_db):
        mock_db.description = [
            ("id",), ("cluster_id",), ("trace_data",), ("created_at",),
        ]
        mock_db.fetchone.return_value = (1, "cluster-1", json.dumps({"step": "1"}), "2025-01-01")

        repo = AIExplainabilityRepository()
        result = repo.create_trace(cluster_id="cluster-1", trace_data={"step": "1"})

        assert result["id"] == 1
        assert result["cluster_id"] == "cluster-1"
        mock_db.execute.assert_called_once()
        assert "INSERT INTO ai_explainability_traces" in mock_db.execute.call_args[0][0]

    def test_raises_on_failure(self, mock_db):
        mock_db.execute.side_effect = Exception("DB error")

        repo = AIExplainabilityRepository()
        with pytest.raises(Exception, match="DB error"):
            repo.create_trace(cluster_id="cluster-1", trace_data={"step": "1"})


class TestGetExplanation:
    def test_returns_dict(self, mock_db):
        mock_db.fetchone.return_value = (1, "cluster-1", "explanation", "gpt-4", 150, "2025-01-01")

        repo = AIExplainabilityRepository()
        result = repo.get_explanation(cluster_id="cluster-1")

        assert result["id"] == 1
        assert result["cluster_id"] == "cluster-1"
        mock_db.execute.assert_called_once()

    def test_returns_none_when_not_found(self, mock_db):
        mock_db.fetchone.return_value = None

        repo = AIExplainabilityRepository()
        result = repo.get_explanation(cluster_id="cluster-1")

        assert result is None

    def test_raises_on_failure(self, mock_db):
        mock_db.execute.side_effect = Exception("DB error")

        repo = AIExplainabilityRepository()
        with pytest.raises(Exception, match="DB error"):
            repo.get_explanation(cluster_id="cluster-1")


class TestGetTrace:
    def test_returns_dict_with_json_loaded_trace_data(self, mock_db):
        mock_db.description = [
            ("id",), ("cluster_id",), ("trace_data",), ("created_at",),
        ]
        mock_db.fetchone.return_value = (1, "cluster-1", json.dumps({"key": "value"}), "2025-01-01")

        repo = AIExplainabilityRepository()
        result = repo.get_trace(cluster_id="cluster-1")

        assert result["id"] == 1
        assert result["trace_data"] == {"key": "value"}

    def test_returns_none_when_not_found(self, mock_db):
        mock_db.fetchone.return_value = None

        repo = AIExplainabilityRepository()
        result = repo.get_trace(cluster_id="cluster-1")

        assert result is None

    def test_raises_on_failure(self, mock_db):
        mock_db.execute.side_effect = Exception("DB error")

        repo = AIExplainabilityRepository()
        with pytest.raises(Exception, match="DB error"):
            repo.get_trace(cluster_id="cluster-1")


class TestClose:
    def test_releases_connection(self):
        mock_conn = MagicMock()
        mock_conn.closed = False

        mock_db_instance = MagicMock()

        with patch(
            "database.repositories.ai_explainability_repository.get_db",
            return_value=mock_db_instance,
        ):
            repo = AIExplainabilityRepository()
            repo._db = mock_conn

            repo.close()

            mock_db_instance.release_connection.assert_called_once_with(mock_conn)
            assert repo._db is None

    def test_does_nothing_when_db_is_none(self):
        repo = AIExplainabilityRepository()

        repo.close()

        assert repo._db is None
