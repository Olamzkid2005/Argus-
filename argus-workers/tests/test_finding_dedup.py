"""Tests for finding deduplication (ON CONFLICT DO NOTHING)."""
from unittest.mock import MagicMock

import pytest

from database.repositories.finding_repository import FindingRepository


class TestFindingDedup:
    """Test that duplicate findings are handled correctly."""

    def test_create_finding_no_duplicate(self):
        """Test creating a unique finding succeeds and returns new ID."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # First fetchone (COUNT(*) soft limit check) returns (0,) — within limit.
        # Second fetchone (after UPDATE legacy check) returns None → no legacy row.
        # Third fetchone (after INSERT) returns the new UUID.
        mock_cursor.fetchone.side_effect = [(0,), None, ("new-uuid",)]
        mock_conn.cursor.return_value = mock_cursor

        repo = FindingRepository()
        repo._get_connection = MagicMock(return_value=mock_conn)
        repo._release_connection = MagicMock()

        result = repo.create_finding(
            engagement_id="eng-1",
            finding_type="xss",
            severity="HIGH",
            endpoint="https://example.com",
            evidence={"payload": "<script>"},
            confidence=0.9,
            source_tool="nuclei",
        )

        assert result == "new-uuid"
        insert_calls = [c for c in mock_cursor.execute.call_args_list if "INSERT" in c[0][0]]
        assert len(insert_calls) == 1
        insert_sql = insert_calls[0][0][0]
        assert "ON CONFLICT" in insert_sql

    def test_create_finding_duplicate_conflict(self):
        """Test creating a duplicate returns existing finding ID via ON CONFLICT RETURNING."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # First fetchone (COUNT(*) soft limit check) returns (0,) — within limit.
        # Second fetchone (after UPDATE legacy check) returns None → no legacy row.
        # Third fetchone (after INSERT with ON CONFLICT) returns existing id via RETURNING.
        mock_cursor.fetchone.side_effect = [(0,), None, ("existing-id",)]
        mock_conn.cursor.return_value = mock_cursor

        repo = FindingRepository()
        repo._get_connection = MagicMock(return_value=mock_conn)
        repo._release_connection = MagicMock()

        result = repo.create_finding(
            engagement_id="eng-1",
            finding_type="xss",
            severity="HIGH",
            endpoint="https://example.com",
            evidence={"payload": "<script>"},
            confidence=0.9,
            source_tool="nuclei",
        )

        assert result == "existing-id"
        insert_calls = [c for c in mock_cursor.execute.call_args_list if "INSERT" in c[0][0]]
        assert len(insert_calls) == 1

    def test_create_finding_commit_after_insert(self):
        """Test that commit is called after successful insert."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [(0,), None, ("new-uuid",)]
        mock_conn.cursor.return_value = mock_cursor

        repo = FindingRepository()
        repo._get_connection = MagicMock(return_value=mock_conn)
        repo._release_connection = MagicMock()

        repo.create_finding(
            engagement_id="eng-1",
            finding_type="xss",
            severity="HIGH",
            endpoint="https://example.com",
            evidence={"payload": "<script>"},
            confidence=0.9,
            source_tool="nuclei",
        )

        mock_conn.commit.assert_called_once()

    def test_create_finding_rollback_on_error(self):
        """Test that rollback is called when an exception occurs."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("DB error")
        mock_conn.cursor.return_value = mock_cursor

        repo = FindingRepository()
        repo._get_connection = MagicMock(return_value=mock_conn)

        with pytest.raises(Exception, match="DB error"):
            repo.create_finding(
                engagement_id="eng-1",
                finding_type="xss",
                severity="HIGH",
                endpoint="https://example.com",
                evidence={"payload": "<script>"},
                confidence=0.9,
                source_tool="nuclei",
            )

        mock_conn.rollback.assert_called_once()

    def test_create_finding_returns_str_id(self):
        """Test that the returned ID is always a string."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [(0,), None, ("some-uuid",)]
        mock_conn.cursor.return_value = mock_cursor

        repo = FindingRepository()
        repo._get_connection = MagicMock(return_value=mock_conn)
        repo._release_connection = MagicMock()

        result = repo.create_finding(
            engagement_id="eng-1",
            finding_type="xss",
            severity="HIGH",
            endpoint="https://example.com",
            evidence={"payload": "<script>"},
            confidence=0.9,
            source_tool="nuclei",
        )

        assert isinstance(result, str)
