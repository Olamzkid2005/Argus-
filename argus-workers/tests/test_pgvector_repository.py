"""Tests for PGVectorRepository"""

from unittest.mock import MagicMock, patch

import pytest

from database.repositories.pgvector_repository import PGVectorRepository


@pytest.fixture
def repo():
    return PGVectorRepository("postgresql://localhost/test")


class TestCheckPgvectorAvailable:
    """Tests for PGVectorRepository.check_pgvector_available()."""

    def test_returns_true_when_extension_exists(self, repo):
        """Returns True when pg_extension has a 'vector' row."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.return_value.__enter__.return_value = mock_cursor
            assert repo.check_pgvector_available() is True

    def test_returns_false_when_extension_missing(self, repo):
        """Returns False when pg_extension has no 'vector' row."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.return_value.__enter__.return_value = mock_cursor
            assert repo.check_pgvector_available() is False

    def test_returns_false_on_exception(self, repo):
        """Returns False and logs a warning when the query fails."""
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.side_effect = Exception("connection error")
            assert repo.check_pgvector_available() is False


class TestStoreEmbedding:
    """Tests for PGVectorRepository.store_embedding()."""

    def test_returns_false_when_pgvector_unavailable(self, repo):
        """Returns False immediately when pgvector is not available."""
        with patch.object(repo, "check_pgvector_available", return_value=False):
            assert repo.store_embedding("fid", "eid", [0.0] * 1536, "text") is False

    def test_validates_embedding_is_list_of_numbers(self, repo):
        """Returns False when embedding is not a list of numeric values."""
        with patch.object(repo, "check_pgvector_available", return_value=True):
            assert repo.store_embedding("fid", "eid", "not_a_list", "text") is False
            assert repo.store_embedding("fid", "eid", ["a", "b"], "text") is False

    def test_validates_embedding_dimensions(self, repo):
        """Returns False when embedding length does not match EMBEDDING_DIMENSIONS."""
        with patch.object(repo, "check_pgvector_available", return_value=True):
            assert repo.store_embedding("fid", "eid", [0.0] * 100, "text") is False

    def test_returns_false_when_finding_not_found(self, repo):
        """Returns False when UPDATE affects zero rows."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        with (
            patch.object(repo, "check_pgvector_available", return_value=True),
            patch("database.repositories.pgvector_repository.db_cursor") as mock,
        ):
            mock.return_value.__enter__.return_value = mock_cursor
            assert repo.store_embedding("fid", "eid", [0.0] * 1536, "text") is False

    def test_stores_successfully(self, repo):
        """Returns True when UPDATE affects one row."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        with (
            patch.object(repo, "check_pgvector_available", return_value=True),
            patch("database.repositories.pgvector_repository.db_cursor") as mock,
        ):
            mock.return_value.__enter__.return_value = mock_cursor
            assert repo.store_embedding("fid", "eid", [0.0] * 1536, "text") is True
            sql = mock_cursor.execute.call_args[0][0]
            assert "UPDATE findings" in sql
            assert "embedding" in sql


class TestFindSimilarFindings:
    """Tests for PGVectorRepository.find_similar_findings()."""

    def test_returns_empty_when_pgvector_unavailable(self, repo):
        """Returns empty list immediately when pgvector is not available."""
        with patch.object(repo, "check_pgvector_available", return_value=False):
            assert repo.find_similar_findings("fid", "eid") == []

    def test_returns_empty_when_source_finding_has_no_embedding(self, repo):
        """Returns empty list when source finding has no embedding."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        with (
            patch.object(repo, "check_pgvector_available", return_value=True),
            patch("database.repositories.pgvector_repository.db_cursor") as mock,
        ):
            mock.return_value.__enter__.return_value = mock_cursor
            assert repo.find_similar_findings("fid", "eid") == []

    def test_returns_results(self, repo):
        """Returns similar findings with similarity scores."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("[0.1,0.2,0.3]",)
        mock_cursor.fetchall.return_value = [
            ("r1", "xss", "high", "/api/login", "eid2", 0.92),
            ("r2", "sqli", "critical", "/api/query", "eid2", 0.87),
        ]
        with (
            patch.object(repo, "check_pgvector_available", return_value=True),
            patch("database.repositories.pgvector_repository.db_cursor") as mock,
        ):
            mock.return_value.__enter__.return_value = mock_cursor
            results = repo.find_similar_findings("fid", "eid")

        assert len(results) == 2
        assert results[0]["id"] == "r1"
        assert results[0]["similarity"] == 0.92
        assert results[1]["type"] == "sqli"


class TestFindSimilarByText:
    """Tests for PGVectorRepository.find_similar_by_text()."""

    def test_returns_results_with_generate_embedding_fallback(self, repo):
        """Returns results when embedding generation succeeds."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("r1", "xss", "high", "/api/login", "eid2", 0.85),
        ]
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.return_value.__enter__.return_value = mock_cursor
            results = repo.find_similar_by_text("sql injection in login", "eid")

        assert len(results) == 1
        assert results[0]["id"] == "r1"

    def test_falls_back_to_find_similar_fallback(self, repo):
        """Falls back to keyword matching when embedding generation returns None."""
        with (
            patch.object(repo, "generate_embedding_fallback", return_value=None),
            patch.object(
                repo,
                "_find_similar_fallback",
                return_value=[{"id": "r1", "match_type": "keyword_fallback"}],
            ) as mock_fallback,
        ):
            results = repo.find_similar_by_text("sql injection", "eid")

        mock_fallback.assert_called_once()
        assert results[0]["id"] == "r1"
        assert results[0]["match_type"] == "keyword_fallback"


class TestGenerateEmbeddingFallback:
    """Tests for PGVectorRepository.generate_embedding_fallback()."""

    def test_returns_correct_dimensions(self, repo):
        """Returns a list with EMBEDDING_DIMENSIONS float values."""
        embedding = repo.generate_embedding_fallback("test text")
        assert isinstance(embedding, list)
        assert len(embedding) == 1536
        assert all(isinstance(v, float) for v in embedding)

    def test_deterministic_for_same_input(self, repo):
        """Same input text produces the same embedding."""
        e1 = repo.generate_embedding_fallback("hello world")
        e2 = repo.generate_embedding_fallback("hello world")
        assert e1 == e2

    def test_different_input_produces_different_embedding(self, repo):
        """Different input text produces a different embedding."""
        e1 = repo.generate_embedding_fallback("hello world")
        e2 = repo.generate_embedding_fallback("goodbye world")
        assert e1 != e2


class TestFindSimilarFallback:
    """Tests for PGVectorRepository._find_similar_fallback()."""

    def test_returns_results_with_keyword_matching(self, repo):
        """Returns results with keyword fallback match_type."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("r1", "xss", "high", "/api/login", "eid2", 0.5),
        ]
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.return_value.__enter__.return_value = mock_cursor
            results = repo._find_similar_fallback(
                "sql injection vulnerability in login page", "eid", 0.5, 10
            )

        assert len(results) == 1
        assert results[0]["match_type"] == "keyword_fallback"
        assert results[0]["similarity"] == 0.5

    def test_returns_empty_with_no_keywords(self, repo):
        """Returns empty list when all words are <= 3 characters."""
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock_cursor = MagicMock()
            mock.return_value.__enter__.return_value = mock_cursor
            results = repo._find_similar_fallback("a an the", "eid", 0.5, 10)
        assert results == []


class TestGetFindingsWithEmbeddings:
    """Tests for PGVectorRepository.get_findings_with_embeddings()."""

    def test_returns_findings_list(self, repo):
        """Returns list of findings that have embeddings."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("f1", "xss", "high", "/api/login", "[0.1,0.2]"),
            ("f2", "sqli", "critical", "/api/query", "[0.3,0.4]"),
        ]
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.return_value.__enter__.return_value = mock_cursor
            results = repo.get_findings_with_embeddings("eid")

        assert len(results) == 2
        assert results[0]["id"] == "f1"
        assert results[0]["has_embedding"] is True
        assert results[1]["type"] == "sqli"

    def test_returns_empty_list_when_no_embeddings(self, repo):
        """Returns empty list when no findings have embeddings."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.return_value.__enter__.return_value = mock_cursor
            results = repo.get_findings_with_embeddings("eid")
        assert results == []


class TestDeleteEmbeddings:
    """Tests for PGVectorRepository.delete_embeddings()."""

    def test_returns_count_of_deleted(self, repo):
        """Returns the number of embeddings set to NULL."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.return_value.__enter__.return_value = mock_cursor
            assert repo.delete_embeddings("eid") == 5

    def test_returns_zero_when_no_embeddings(self, repo):
        """Returns 0 when no embeddings match the engagement."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        with patch("database.repositories.pgvector_repository.db_cursor") as mock:
            mock.return_value.__enter__.return_value = mock_cursor
            assert repo.delete_embeddings("eid") == 0
