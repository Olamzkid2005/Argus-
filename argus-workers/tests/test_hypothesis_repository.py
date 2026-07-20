"""\
Tests for Hypothesis Repository.

Requirements: B.11, B.12
Covers CRUD operations for the hypotheses table, including:
- create() with ON CONFLICT DO NOTHING
- get_by_engagement() with and without status filter
- update() with partial updates
- update() with invalid column rejection
- delete_by_engagement()
- ON CONFLICT dedup for grouped and single-finding hypotheses
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from tool_core._compat import utc

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.repositories.hypothesis_repository import HypothesisRepository

# ── Shared helpers ──────────────────────────────────────────────────────


def _make_hypothesis(
    engagement_id: str,
    root_cause_key: str | None = None,
    source_finding_id: str | None = None,
    **overrides,
) -> dict:
    """Helper to build a hypothesis dict with sensible defaults."""
    now = datetime.now(utc).isoformat()
    hyp = {
        "id": str(uuid4()),
        "engagement_id": engagement_id,
        "description": "Test hypothesis",
        "root_cause_key": root_cause_key,
        "source_finding_id": source_finding_id,
        "confidence": 0.75,
        "status": "UNVERIFIED",
        "verification_steps": [
            {
                "description": "Run sqlmap to verify SQL injection",
                "tool": "sqlmap",
                "arguments": {"target": "https://example.com", "parameter": "id"},
                "expected": "findings_count > 0",
            }
        ],
        "finding_ids": [],
        "supporting_finding_ids": [],
        "refuting_finding_ids": [],
        "suggested_tools": ["sqlmap", "verification_agent"],
        "created_at": now,
        "updated_at": now,
    }
    hyp.update(overrides)
    return hyp


# ── Mock helpers (used by mock-based test classes) ──────────────────────


def _make_mock_cursor():
    """Create a mock cursor that returns empty results by default."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.rowcount = 0
    cursor.description = None
    return cursor


def _make_mock_connection(cursor=None):
    """Create a mock connection with a given cursor."""
    if cursor is None:
        cursor = _make_mock_cursor()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    # Handle both `with conn.cursor() as cur:` and direct cursor calls
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = None
    return conn, cursor


class MockRow(dict):
    """Simulates a row returned by RealDictCursor."""
    pass


# ── Fixtures (for integration tests) ────────────────────────────────────


@pytest.fixture
def repo():
    """Create a HypothesisRepository with test database connection."""
    connection_string = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://test:test@localhost:5432/test_db",
    )
    return HypothesisRepository(connection_string)


@pytest.fixture
def engagement_id():
    """Return a unique engagement ID per test."""
    return str(uuid4())


# ═══════════════════════════════════════════════════════════════════════════
# PART 1 — Unit tests (no database required)
# ═══════════════════════════════════════════════════════════════════════════


class TestHypothesisRepositoryUnit:
    """Unit tests that do not require a live database."""

    def test_table_name(self):
        """Repository should reference the correct table."""
        repo = HypothesisRepository("postgresql://localhost/test")
        assert repo.table_name == "hypotheses"

    def test_id_column(self):
        """Repository should use id as the primary key column."""
        repo = HypothesisRepository("postgresql://localhost/test")
        assert repo.id_column == "id"

    def test_is_base_repository_subclass(self):
        """HypothesisRepository should inherit from BaseRepository."""
        from database.repositories.base import BaseRepository
        assert issubclass(HypothesisRepository, BaseRepository)

    def test_hypotheses_in_allowed_table_names(self):
        """hypotheses must be in BaseRepository's allowed table names."""
        from database.repositories.base import _ALLOWED_TABLE_NAMES
        assert "hypotheses" in _ALLOWED_TABLE_NAMES

    def test_migration_file_exists(self):
        """Migration 019_add_hypotheses.sql must exist."""
        path = os.path.join(
            os.path.dirname(__file__), "..", "database", "migrations", "019_add_hypotheses.sql"
        )
        assert os.path.exists(path), f"Migration not found at {path}"

    def test_migration_sql_structure(self):
        """The migration SQL must have valid structure."""
        path = os.path.join(
            os.path.dirname(__file__), "..", "database", "migrations", "019_add_hypotheses.sql"
        )
        with open(path) as f:
            sql = f.read()

        begins = len(re.findall(r'\bBEGIN\b', sql))
        commits = len(re.findall(r'\bCOMMIT\b', sql))
        assert begins == commits, f"BEGIN/COMMIT mismatch: {begins} vs {commits}"

        assert "CREATE TABLE IF NOT EXISTS hypotheses" in sql
        assert "id UUID PRIMARY KEY" in sql
        assert "REFERENCES engagements(id)" in sql
        assert "ON DELETE CASCADE" in sql
        assert "CHECK (status IN" in sql
        assert "CHECK (confidence >=" in sql
        assert "JSONB" in sql
        assert "idx_hypotheses_engagement_root_cause" in sql
        assert "idx_hypotheses_engagement_source_finding" in sql
        assert "idx_hypotheses_engagement_id" in sql
        assert "idx_hypotheses_status" in sql


# ═══════════════════════════════════════════════════════════════════════════
# PART 2 — Mock-based unit tests (verify SQL structure without a live DB)
# ═══════════════════════════════════════════════════════════════════════════


class TestHypothesisRepositoryCreateMock:
    """Mock-based tests for HypothesisRepository.create()."""

    @staticmethod
    def _make_hyp_kwargs(**overrides) -> dict:
        defaults = {
            "id": "hyp-1",
            "engagement_id": "eng-1",
            "description": "Test hypothesis",
            "root_cause_key": "cwe:89",
            "source_finding_id": None,
            "confidence": 0.75,
            "status": "UNVERIFIED",
            "verification_steps": [{"tool": "sqlmap", "arguments": {}, "expected": "ok"}],
            "finding_ids": [],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
            "suggested_tools": ["sqlmap"],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        defaults.update(overrides)
        return defaults

    def test_create_returns_dict(self):
        """create() returns the inserted row as a dict."""
        repo = HypothesisRepository()
        hyp = self._make_hyp_kwargs()
        row = MockRow(hyp)
        row["verification_steps"] = hyp["verification_steps"]
        row["finding_ids"] = hyp["finding_ids"]
        row["supporting_finding_ids"] = hyp["supporting_finding_ids"]
        row["refuting_finding_ids"] = hyp["refuting_finding_ids"]
        row["suggested_tools"] = hyp["suggested_tools"]

        cursor = _make_mock_cursor()
        cursor.fetchone.return_value = row
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            result = repo.create(hyp)

        assert result is not None
        assert result["id"] == "hyp-1"
        assert result["engagement_id"] == "eng-1"

    def test_create_sql_has_required_keywords(self):
        """create() SQL must contain ON CONFLICT, RETURNING *, DO NOTHING."""
        repo = HypothesisRepository()
        hyp = self._make_hyp_kwargs()
        row = MockRow(hyp)
        row["verification_steps"] = hyp["verification_steps"]
        row["finding_ids"] = hyp["finding_ids"]
        row["supporting_finding_ids"] = hyp["supporting_finding_ids"]
        row["refuting_finding_ids"] = hyp["refuting_finding_ids"]
        row["suggested_tools"] = hyp["suggested_tools"]

        cursor = _make_mock_cursor()
        cursor.fetchone.return_value = row
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            repo.create(hyp)

        sql = str(cursor.execute.call_args[0][0])
        assert "ON CONFLICT" in sql
        assert "RETURNING *" in sql
        assert "DO NOTHING" in sql
        assert "root_cause_key" in sql

    def test_create_conflict_returns_existing(self):
        """ON CONFLICT returns the existing row via fallback SELECT."""
        repo = HypothesisRepository()
        hyp = self._make_hyp_kwargs(description="Original")

        existing = MockRow(hyp)
        existing["verification_steps"] = []
        existing["finding_ids"] = []
        existing["supporting_finding_ids"] = []
        existing["refuting_finding_ids"] = []
        existing["suggested_tools"] = []

        cursor = _make_mock_cursor()
        # First fetchone = None (ON CONFLICT RETURNING * yields no row)
        # Second fetchone = existing row (fallback SELECT)
        cursor.fetchone.side_effect = [None, existing]
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            result = repo.create(hyp)

        assert result is not None
        assert result["description"] == "Original"

        # Verify fallback SELECT was executed
        calls = cursor.execute.call_args_list
        assert any("SELECT * FROM hypotheses" in str(c) for c in calls)


class TestHypothesisRepositoryGetMock:
    """Mock-based tests for HypothesisRepository.get_by_engagement()."""

    def test_get_by_engagement_returns_list(self):
        """get_by_engagement() returns a list of dicts."""
        repo = HypothesisRepository()
        row1 = MockRow({"id": "h1", "confidence": 0.9, "status": "UNVERIFIED",
                         "verification_steps": [], "finding_ids": [],
                         "supporting_finding_ids": [], "refuting_finding_ids": [],
                         "suggested_tools": []})
        row2 = MockRow({"id": "h2", "confidence": 0.7, "status": "UNVERIFIED",
                         "verification_steps": [], "finding_ids": [],
                         "supporting_finding_ids": [], "refuting_finding_ids": [],
                         "suggested_tools": []})

        cursor = _make_mock_cursor()
        cursor.fetchall.return_value = [row1, row2]
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            results = repo.get_by_engagement("eng-1")

        assert isinstance(results, list)
        assert len(results) == 2

        sql = str(cursor.execute.call_args[0][0])
        assert "ORDER BY confidence DESC" in sql

    def test_get_by_engagement_empty(self):
        """Empty result set returns empty list."""
        repo = HypothesisRepository()
        cursor = _make_mock_cursor()
        cursor.fetchall.return_value = []
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            results = repo.get_by_engagement("eng-empty")

        assert results == []

    def test_get_by_engagement_with_status_filter(self):
        """get_by_engagement() with status filter adds WHERE clause."""
        repo = HypothesisRepository()
        row = MockRow({"id": "h1", "status": "UNVERIFIED", "confidence": 0.8,
                        "verification_steps": [], "finding_ids": [],
                        "supporting_finding_ids": [], "refuting_finding_ids": [],
                        "suggested_tools": []})

        cursor = _make_mock_cursor()
        cursor.fetchall.return_value = [row]
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            filtered = repo.get_by_engagement("eng-1", status="UNVERIFIED")

        assert len(filtered) == 1
        sql = str(cursor.execute.call_args[0][0])
        assert "AND status = %s" in sql or "AND status =" in sql


class TestHypothesisRepositoryUpdateMock:
    """Mock-based tests for HypothesisRepository.update()."""

    def test_update_returns_dict(self):
        """update() returns the updated row."""
        repo = HypothesisRepository()
        row = MockRow({"id": "hyp-1", "status": "CONFIRMED", "confidence": 0.95,
                        "verification_steps": [], "finding_ids": [],
                        "supporting_finding_ids": [], "refuting_finding_ids": [],
                        "suggested_tools": []})

        cursor = _make_mock_cursor()
        cursor.fetchone.return_value = row
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            result = repo.update("hyp-1", {"status": "CONFIRMED", "confidence": 0.95})

        assert result is not None
        assert result["status"] == "CONFIRMED"

    def test_update_sql_has_required_keywords(self):
        """update() SQL must be UPDATE with RETURNING * and updated_at."""
        repo = HypothesisRepository()
        row = MockRow({"id": "hyp-1", "status": "CONFIRMED",
                        "verification_steps": [], "finding_ids": [],
                        "supporting_finding_ids": [], "refuting_finding_ids": [],
                        "suggested_tools": []})

        cursor = _make_mock_cursor()
        cursor.fetchone.return_value = row
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            repo.update("hyp-1", {"status": "CONFIRMED"})

        sql = str(cursor.execute.call_args[0][0])
        assert sql.strip().upper().startswith("UPDATE")
        assert "RETURNING *" in sql
        assert "WHERE id = %s" in sql
        assert "updated_at = NOW()" in sql

    def test_update_jsonb_fields_use_jsonb_cast(self):
        """JSONB fields in update() use ::jsonb cast."""
        repo = HypothesisRepository()
        row = MockRow({"id": "hyp-1", "verification_steps": [], "suggested_tools": []})

        cursor = _make_mock_cursor()
        cursor.fetchone.return_value = row
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            repo.update("hyp-1", {
                "verification_steps": [{"tool": "jwt_tool"}],
                "suggested_tools": ["jwt_tool"],
            })

        sql = str(cursor.execute.call_args[0][0])
        assert "::jsonb" in sql

    def test_update_nonexistent_returns_none(self):
        """Updating a non-existent ID returns None."""
        repo = HypothesisRepository()
        cursor = _make_mock_cursor()
        cursor.fetchone.return_value = None
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            result = repo.update("nonexistent", {"status": "CONFIRMED"})

        assert result is None

    def test_update_invalid_column_raises_value_error(self):
        """Updating with invalid column names raises ValueError."""
        repo = HypothesisRepository()
        with pytest.raises(ValueError, match="Invalid columns"):
            repo.update("hyp-1", {"invalid_column": "value"})

    def test_update_empty_updates_delegates_to_find_by_id(self):
        """Empty updates dict delegates to find_by_id()."""
        repo = HypothesisRepository()
        row = MockRow({"id": "hyp-1", "description": "Test"})

        cursor = _make_mock_cursor()
        cursor.fetchone.return_value = row
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            result = repo.update("hyp-1", {})

        assert result is not None
        sql = str(cursor.execute.call_args[0][0])
        assert "SELECT" in sql.upper()


class TestHypothesisRepositoryDeleteMock:
    """Mock-based tests for HypothesisRepository.delete_by_engagement()."""

    def test_delete_by_engagement_returns_rowcount(self):
        """delete_by_engagement() returns the number of deleted rows."""
        repo = HypothesisRepository()
        cursor = _make_mock_cursor()
        cursor.rowcount = 3
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            count = repo.delete_by_engagement("eng-1")

        assert count == 3
        sql = str(cursor.execute.call_args[0][0])
        assert sql.strip().upper().startswith("DELETE")
        assert "engagement_id = %s" in sql or "engagement_id =" in sql

    def test_delete_by_engagement_nonexistent_returns_zero(self):
        """Deleting from engagement with no hypotheses returns 0."""
        repo = HypothesisRepository()
        cursor = _make_mock_cursor()
        cursor.rowcount = 0
        conn, _ = _make_mock_connection(cursor)

        with patch.object(repo, "db_operation") as mock_db:
            mock_db.return_value.__enter__.return_value = (conn, cursor)
            count = repo.delete_by_engagement("eng-empty")

        assert count == 0


# ═══════════════════════════════════════════════════════════════════════════
# PART 3 — Integration tests (require TEST_DATABASE_URL)
# ═══════════════════════════════════════════════════════════════════════════


class TestHypothesisRepositoryCreate:
    """Tests for HypothesisRepository.create()."""

    def test_create_hypothesis(self, repo, engagement_id):
        """Create a hypothesis and verify it is returned."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        hyp = _make_hypothesis(engagement_id, root_cause_key="cwe:89")
        created = repo.create(hyp)

        assert created is not None
        assert created["id"] == hyp["id"]
        assert created["engagement_id"] == engagement_id
        assert created["description"] == hyp["description"]
        assert created["root_cause_key"] == "cwe:89"
        assert created["confidence"] == 0.75
        assert created["status"] == "UNVERIFIED"

    def test_create_on_conflict_returns_existing(self, repo, engagement_id):
        """Inserting a duplicate root_cause_key returns the existing row.

        Verifies that the original row's data is preserved (not overwritten
        by the conflicting insert) by passing different data on the second
        call and asserting the first call's values remain.
        """
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        first_hyp = _make_hypothesis(engagement_id, root_cause_key="cwe:79",
                                     description="Original hypothesis")
        first = repo.create(first_hyp)
        assert first is not None
        assert first["description"] == "Original hypothesis"

        # Same engagement_id + root_cause_key → ON CONFLICT DO NOTHING
        # Different description proves the original row is returned
        second_hyp = _make_hypothesis(engagement_id, root_cause_key="cwe:79",
                                      description="Should be ignored")
        second = repo.create(second_hyp)
        assert second is not None
        assert second["id"] == first["id"]
        assert second["description"] == "Original hypothesis"

    def test_create_multiple_unique_keys(self, repo, engagement_id):
        """Different root_cause_keys for same engagement create distinct rows."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        h1 = _make_hypothesis(engagement_id, root_cause_key="cwe:89")
        h2 = _make_hypothesis(engagement_id, root_cause_key="cwe:79")
        c1 = repo.create(h1)
        c2 = repo.create(h2)

        assert c1 is not None
        assert c2 is not None
        assert c1["id"] != c2["id"]

    def test_create_with_source_finding_id(self, repo, engagement_id):
        """Single-finding hypothesis with source_finding_id."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        finding_id = str(uuid4())
        hyp = _make_hypothesis(
            engagement_id,
            root_cause_key=None,
            source_finding_id=finding_id,
        )
        created = repo.create(hyp)
        assert created is not None
        assert created["source_finding_id"] == finding_id

    def test_create_with_jsonb_fields(self, repo, engagement_id):
        """JSONB fields are stored and retrieved correctly."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        hyp = _make_hypothesis(
            engagement_id,
            root_cause_key="cwe:22",
            verification_steps=[
                {"tool": "nuclei", "arguments": {}, "expected": "ok"},
            ],
            finding_ids=["f1", "f2"],
            supporting_finding_ids=["f3"],
            refuting_finding_ids=[],
            suggested_tools=["nuclei", "verification_agent"],
        )
        created = repo.create(hyp)
        assert created is not None
        assert len(created["verification_steps"]) == 1
        assert created["verification_steps"][0]["tool"] == "nuclei"
        assert created["finding_ids"] == ["f1", "f2"]
        assert created["supporting_finding_ids"] == ["f3"]
        assert created["refuting_finding_ids"] == []
        assert "verification_agent" in created["suggested_tools"]


class TestHypothesisRepositoryGetByEngagement:
    """Tests for HypothesisRepository.get_by_engagement()."""

    def test_get_by_engagement_empty(self, repo, engagement_id):
        """Engagement with no hypotheses returns empty list."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        results = repo.get_by_engagement(engagement_id)
        assert results == []

    def test_get_by_engagement_returns_all(self, repo, engagement_id):
        """All hypotheses for an engagement are returned."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        repo.create(_make_hypothesis(engagement_id, root_cause_key="cwe:89"))
        repo.create(_make_hypothesis(engagement_id, root_cause_key="cwe:79"))

        results = repo.get_by_engagement(engagement_id)
        assert len(results) == 2

    def test_get_by_engagement_filters_by_status(self, repo, engagement_id):
        """Filtering by status returns only matching hypotheses."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        repo.create(
            _make_hypothesis(engagement_id, root_cause_key="cwe:89",
                             status="UNVERIFIED")
        )
        repo.create(
            _make_hypothesis(engagement_id, root_cause_key="cwe:79",
                             status="CONFIRMED")
        )

        unverified = repo.get_by_engagement(engagement_id, status="UNVERIFIED")
        assert len(unverified) == 1
        assert unverified[0]["status"] == "UNVERIFIED"

        confirmed = repo.get_by_engagement(engagement_id, status="CONFIRMED")
        assert len(confirmed) == 1
        assert confirmed[0]["status"] == "CONFIRMED"

    def test_get_by_engagement_sorts_by_confidence(self, repo, engagement_id):
        """Results are sorted by confidence descending."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        repo.create(
            _make_hypothesis(engagement_id, root_cause_key="cwe:89",
                             confidence=0.5)
        )
        repo.create(
            _make_hypothesis(engagement_id, root_cause_key="cwe:79",
                             confidence=0.9)
        )
        repo.create(
            _make_hypothesis(engagement_id, root_cause_key="cwe:22",
                             confidence=0.7)
        )

        results = repo.get_by_engagement(engagement_id)
        confidences = [r["confidence"] for r in results]
        assert confidences == sorted(confidences, reverse=True)


class TestHypothesisRepositoryUpdate:
    """Tests for HypothesisRepository.update()."""

    def test_update_status_and_confidence(self, repo, engagement_id):
        """Update status and confidence on a hypothesis."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        hyp = _make_hypothesis(engagement_id, root_cause_key="cwe:89")
        created = repo.create(hyp)
        assert created is not None

        updated = repo.update(created["id"], {
            "status": "CONFIRMED",
            "confidence": 0.95,
        })
        assert updated is not None
        assert updated["status"] == "CONFIRMED"
        assert updated["confidence"] == 0.95

    def test_update_jsonb_fields(self, repo, engagement_id):
        """JSONB fields can be updated via the update method."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        hyp = _make_hypothesis(engagement_id, root_cause_key="cwe:89")
        created = repo.create(hyp)
        assert created is not None

        new_steps = [
            {"tool": "jwt_tool", "arguments": {}, "expected": "ok"},
        ]
        updated = repo.update(created["id"], {
            "verification_steps": new_steps,
            "suggested_tools": ["jwt_tool", "verification_agent"],
        })
        assert updated is not None
        assert len(updated["verification_steps"]) == 1
        assert updated["verification_steps"][0]["tool"] == "jwt_tool"
        assert "jwt_tool" in updated["suggested_tools"]

    def test_update_supporting_finding_ids(self, repo, engagement_id):
        """Append supporting finding IDs via update."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        hyp = _make_hypothesis(engagement_id, root_cause_key="cwe:89")
        created = repo.create(hyp)
        assert created is not None

        updated = repo.update(created["id"], {
            "supporting_finding_ids": ["f1", "f2"],
            "finding_ids": ["f_orig", "f1", "f2"],
        })
        assert updated is not None
        assert "f1" in updated["supporting_finding_ids"]
        assert "f2" in updated["supporting_finding_ids"]

    def test_update_nonexistent_returns_none(self, repo):
        """Updating a non-existent hypothesis returns None."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        result = repo.update(str(uuid4()), {"status": "CONFIRMED"})
        assert result is None

    def test_update_with_invalid_column_raises(self, repo, engagement_id):
        """Updating with invalid column names raises ValueError."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        hyp = _make_hypothesis(engagement_id, root_cause_key="cwe:89")
        created = repo.create(hyp)
        assert created is not None

        with pytest.raises(ValueError, match="Invalid columns"):
            repo.update(created["id"], {"nonexistent_column": "value"})

    def test_update_sets_updated_at(self, repo, engagement_id):
        """updated_at is updated to NOW() while created_at is preserved."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        hyp = _make_hypothesis(engagement_id, root_cause_key="cwe:89")
        created = repo.create(hyp)
        assert created is not None

        updated = repo.update(created["id"], {"confidence": 0.5})
        assert updated is not None
        # updated_at should differ from created_at (SQL sets updated_at = NOW())
        assert updated["updated_at"] != updated["created_at"]
        # created_at should be preserved unchanged
        assert str(updated["created_at"]) == str(created["created_at"])


class TestHypothesisRepositoryDeleteByEngagement:
    """Tests for HypothesisRepository.delete_by_engagement()."""

    def test_delete_by_engagement(self, repo, engagement_id):
        """Deleting hypotheses for an engagement removes them."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        repo.create(_make_hypothesis(engagement_id, root_cause_key="cwe:89"))
        repo.create(_make_hypothesis(engagement_id, root_cause_key="cwe:79"))

        deleted = repo.delete_by_engagement(engagement_id)
        assert deleted == 2

        remaining = repo.get_by_engagement(engagement_id)
        assert remaining == []

    def test_delete_by_engagement_other_untouched(self, repo, engagement_id):
        """Deleting one engagement's hypotheses does not affect another."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        other_id = str(uuid4())
        repo.create(_make_hypothesis(engagement_id, root_cause_key="cwe:89"))
        repo.create(_make_hypothesis(other_id, root_cause_key="cwe:79"))

        deleted = repo.delete_by_engagement(engagement_id)
        assert deleted == 1

        other = repo.get_by_engagement(other_id)
        assert len(other) == 1

    def test_delete_nonexistent_engagement(self, repo):
        """Deleting hypotheses for an engagement with none returns 0."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        deleted = repo.delete_by_engagement(str(uuid4()))
        assert deleted == 0


class TestHypothesisRepositoryWorkflow:
    """End-to-end CRUD workflow for hypotheses."""

    def test_full_crud_cycle(self, repo, engagement_id):
        """Create, read, update, delete cycle for hypotheses."""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")

        # Create
        h1 = _make_hypothesis(engagement_id, root_cause_key="cwe:89")
        h2 = _make_hypothesis(engagement_id, root_cause_key="cwe:79")
        c1 = repo.create(h1)
        c2 = repo.create(h2)
        assert c1 is not None
        assert c2 is not None

        # Read (all)
        all_h = repo.get_by_engagement(engagement_id)
        assert len(all_h) == 2

        # Read (filtered)
        unverified = repo.get_by_engagement(engagement_id, status="UNVERIFIED")
        assert len(unverified) == 2

        # Update
        repo.update(c1["id"], {"status": "CONFIRMED", "confidence": 0.95})
        repo.update(c2["id"], {"status": "REJECTED", "confidence": 0.15})

        confirmed = repo.get_by_engagement(engagement_id, status="CONFIRMED")
        assert len(confirmed) == 1
        assert confirmed[0]["id"] == c1["id"]

        rejected = repo.get_by_engagement(engagement_id, status="REJECTED")
        assert len(rejected) == 1
        assert rejected[0]["id"] == c2["id"]

        # Delete
        deleted = repo.delete_by_engagement(engagement_id)
        assert deleted == 2

        final = repo.get_by_engagement(engagement_id)
        assert final == []
