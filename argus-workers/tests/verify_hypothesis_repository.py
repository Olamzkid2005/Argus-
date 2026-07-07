"""
Standalone verification script for HypothesisRepository.

Mocks the database layer so we can verify the repository methods
generate correct SQL queries and handle edge cases properly
without requiring a live PostgreSQL connection.

Run with: python3 -m tests.verify_hypothesis_repository
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.repositories.hypothesis_repository import HypothesisRepository

# ── Test helpers ──────────────────────────────────────────────────────

passed = 0
failed = 0


def test(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def make_mock_cursor():
    """Create a mock cursor that returns empty results by default."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.rowcount = 0
    cursor.description = None
    return cursor


def make_mock_connection(cursor=None):
    """Create a mock connection with a given cursor."""
    if cursor is None:
        cursor = make_mock_cursor()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = None
    return conn, cursor


class FakeRealDictRow(dict):
    """Simulates a row returned by RealDictCursor."""
    pass


# ── Tests ─────────────────────────────────────────────────────────────


def test_create():
    """Test HypothesisRepository.create() generates correct SQL."""
    repo = HypothesisRepository()

    hyp = {
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

    cursor = make_mock_cursor()
    # Simulate successful insert
    row = FakeRealDictRow(hyp)
    row["verification_steps"] = hyp["verification_steps"]
    row["finding_ids"] = hyp["finding_ids"]
    row["supporting_finding_ids"] = hyp["supporting_finding_ids"]
    row["refuting_finding_ids"] = hyp["refuting_finding_ids"]
    row["suggested_tools"] = hyp["suggested_tools"]
    cursor.fetchone.return_value = row
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        result = repo.create(hyp)

    test("create returns dict", result is not None)
    test("create returns correct id", result and result["id"] == "hyp-1")
    test("create returns correct engagement", result and result["engagement_id"] == "eng-1")
    test("create uses ON CONFLICT", any(
        "ON CONFLICT" in str(c)
        for c in cursor.execute.call_args_list
    ) if cursor.execute.call_args else False, "ON CONFLICT not found in SQL")


def test_create_conflict_returns_existing():
    """When a conflict occurs, the existing row is returned."""
    repo = HypothesisRepository()

    # First call: insert succeeds
    hyp = {
        "id": "hyp-1",
        "engagement_id": "eng-1",
        "description": "Original",
        "root_cause_key": "cwe:89",
        "source_finding_id": None,
        "confidence": 0.75,
        "status": "UNVERIFIED",
        "verification_steps": [],
        "finding_ids": [],
        "supporting_finding_ids": [],
        "refuting_finding_ids": [],
        "suggested_tools": [],
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }

    # Second call: ON CONFLICT returns nothing → fallback SELECT returns existing
    existing_row = FakeRealDictRow({**hyp, "id": "hyp-1", "description": "Original"})
    existing_row["verification_steps"] = []
    existing_row["finding_ids"] = []
    existing_row["supporting_finding_ids"] = []
    existing_row["refuting_finding_ids"] = []
    existing_row["suggested_tools"] = []

    cursor = make_mock_cursor()
    cursor.fetchone.side_effect = [None, existing_row]  # No RETURNING row → fallback SELECT
    conn, _ = make_mock_connection(cursor)

    # Verify the fallback SELECT query
    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        result = repo.create(hyp)

    test("conflict returns a result", result is not None)
    test("conflict returns original description",
         result and result.get("description") == "Original")

    # Check that the second execute was the fallback SELECT
    calls = cursor.execute.call_args_list
    has_fallback = any("SELECT * FROM hypotheses" in str(c) for c in calls)
    test("create fallback SELECT exists", has_fallback)


def test_create_on_conflict_sql():
    """Verify the ON CONFLICT clause targets the correct unique index."""
    repo = HypothesisRepository()
    hyp = {
        "id": "hyp-1",
        "engagement_id": "eng-1",
        "description": "Test",
        "root_cause_key": "cwe:89",
        "source_finding_id": None,
        "confidence": 0.5,
        "status": "UNVERIFIED",
        "verification_steps": [],
        "finding_ids": [],
        "supporting_finding_ids": [],
        "refuting_finding_ids": [],
        "suggested_tools": [],
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }

    cursor = make_mock_cursor()
    row = FakeRealDictRow(hyp)
    row["verification_steps"] = []
    row["finding_ids"] = []
    row["supporting_finding_ids"] = []
    row["refuting_finding_ids"] = []
    row["suggested_tools"] = []
    cursor.fetchone.return_value = row
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        repo.create(hyp)

    # Extract the SQL from the first execute call
    if cursor.execute.call_args:
        sql = str(cursor.execute.call_args[0][0])
        test("create SQL uses RETURNING *", "RETURNING *" in sql)
        test("create SQL uses ON CONFLICT with root_cause_key",
             "root_cause_key" in sql)
        test("create SQL uses DO NOTHING", "DO NOTHING" in sql)


def test_get_by_engagement():
    """Test get_by_engagement() generates correct SQL."""
    repo = HypothesisRepository()

    cursor = make_mock_cursor()
    row1 = FakeRealDictRow({"id": "h1", "engagement_id": "eng-1", "confidence": 0.9,
                            "status": "UNVERIFIED", "description": "Hyp 1",
                            "verification_steps": [], "finding_ids": [],
                            "supporting_finding_ids": [], "refuting_finding_ids": [],
                            "suggested_tools": []})
    row2 = FakeRealDictRow({"id": "h2", "engagement_id": "eng-1", "confidence": 0.7,
                            "status": "UNVERIFIED", "description": "Hyp 2",
                            "verification_steps": [], "finding_ids": [],
                            "supporting_finding_ids": [], "refuting_finding_ids": [],
                            "suggested_tools": []})
    cursor.fetchall.return_value = [row1, row2]
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        results = repo.get_by_engagement("eng-1")

    test("get_by_engagement returns list", isinstance(results, list))
    test("get_by_engagement returns 2 items", len(results) == 2)

    # Check SQL uses ORDER BY confidence DESC
    if cursor.execute.call_args:
        sql = str(cursor.execute.call_args[0][0])
        test("get_by_engagement SQL sorts by confidence",
             "ORDER BY confidence DESC" in sql)

    # Test with status filter
    cursor2 = make_mock_cursor()
    cursor2.fetchall.return_value = [row1]
    conn2, _ = make_mock_connection(cursor2)

    with patch.object(repo, "db_operation") as mock_db_op2:
        mock_db_op2.return_value.__enter__.return_value = (conn2, cursor2)
        filtered = repo.get_by_engagement("eng-1", status="UNVERIFIED")

    test("get_by_engagement with status returns list", isinstance(filtered, list))
    if cursor2.execute.call_args:
        sql2 = str(cursor2.execute.call_args[0][0])
        test("get_by_engagement SQL filters by status",
             "AND status = %s" in sql2 or 'AND status =' in sql2)


def test_get_by_engagement_empty():
    """Empty result set returns empty list."""
    repo = HypothesisRepository()
    cursor = make_mock_cursor()
    cursor.fetchall.return_value = []
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        results = repo.get_by_engagement("eng-empty")

    test("get_by_engagement empty returns []", results == [])


def test_update():
    """Test update() generates correct SQL."""
    repo = HypothesisRepository()

    cursor = make_mock_cursor()
    updated_row = FakeRealDictRow({"id": "hyp-1", "engagement_id": "eng-1",
                                    "description": "Updated",
                                    "confidence": 0.95, "status": "CONFIRMED",
                                    "verification_steps": [], "finding_ids": [],
                                    "supporting_finding_ids": [],
                                    "refuting_finding_ids": [],
                                    "suggested_tools": []})
    cursor.fetchone.return_value = updated_row
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        result = repo.update("hyp-1", {"status": "CONFIRMED", "confidence": 0.95})

    test("update returns dict", result is not None)
    test("update returns CONFIRMED status",
         result and result.get("status") == "CONFIRMED")

    if cursor.execute.call_args:
        sql = str(cursor.execute.call_args[0][0])
        test("update SQL is UPDATE", sql.strip().upper().startswith("UPDATE"))
        test("update SQL uses RETURNING *", "RETURNING *" in sql)
        test("update SQL has WHERE id = %s", "WHERE id = %s" in sql)
        test("update SQL sets updated_at", "updated_at = NOW()" in sql)


def test_update_jsonb():
    """Test update() correctly serializes JSONB fields."""
    repo = HypothesisRepository()

    cursor = make_mock_cursor()
    updated_row = FakeRealDictRow({"id": "hyp-1", "verification_steps": [],
                                    "suggested_tools": []})
    cursor.fetchone.return_value = updated_row
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        repo.update("hyp-1", {
            "verification_steps": [{"tool": "jwt_tool"}],
            "suggested_tools": ["jwt_tool"],
        })

    if cursor.execute.call_args:
        sql = str(cursor.execute.call_args[0][0])
        test("update JSONB uses ::jsonb cast", "::jsonb" in sql)


def test_update_nonexistent():
    """Updating a non-existent hypothesis returns None."""
    repo = HypothesisRepository()
    cursor = make_mock_cursor()
    cursor.fetchone.return_value = None
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        result = repo.update("nonexistent", {"status": "CONFIRMED"})

    test("update nonexistent returns None", result is None)


def test_update_invalid_column():
    """Updating with invalid column names raises ValueError."""
    repo = HypothesisRepository()
    try:
        repo.update("hyp-1", {"invalid_column": "value"})
        test("update invalid column raises ValueError", False, "No exception raised")
    except ValueError:
        test("update invalid column raises ValueError", True)


def test_update_empty_updates():
    """Updating with empty updates dict delegates to find_by_id."""
    repo = HypothesisRepository()

    cursor = make_mock_cursor()
    row = FakeRealDictRow({"id": "hyp-1", "description": "Test"})
    cursor.fetchone.return_value = row
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        result = repo.update("hyp-1", {})

    test("update empty returns dict (delegates to find_by_id)", result is not None)
    # find_by_id formats SQL using psycopg2.sql.SQL with quoted identifiers
    # e.g. SELECT * FROM "hypotheses" WHERE "id" = %s
    if cursor.execute.call_args:
        sql = str(cursor.execute.call_args[0][0])
        test("update empty delegates to find_by_id (SELECT query)",
             "SELECT" in sql.upper() or "select" in sql.lower())


def test_delete_by_engagement():
    """Test delete_by_engagement() generates correct SQL."""
    repo = HypothesisRepository()

    cursor = make_mock_cursor()
    cursor.rowcount = 3
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        count = repo.delete_by_engagement("eng-1")

    test("delete_by_engagement returns count", count == 3)

    if cursor.execute.call_args:
        sql = str(cursor.execute.call_args[0][0])
        test("delete SQL is DELETE", sql.strip().upper().startswith("DELETE"))
        test("delete SQL filters by engagement_id",
             "engagement_id = %s" in sql or "engagement_id =" in sql)


def test_delete_by_engagement_nonexistent():
    """Deleting from engagement with no hypotheses returns 0."""
    repo = HypothesisRepository()

    cursor = make_mock_cursor()
    cursor.rowcount = 0
    conn, _ = make_mock_connection(cursor)

    with patch.object(repo, "db_operation") as mock_db_op:
        mock_db_op.return_value.__enter__.return_value = (conn, cursor)
        count = repo.delete_by_engagement("eng-empty")

    test("delete_by_engagement nonexistent returns 0", count == 0)


def test_repository_properties():
    """Test base repository properties."""
    repo = HypothesisRepository()
    test("table_name is 'hypotheses'", repo.table_name == "hypotheses")
    test("id_column is 'id'", repo.id_column == "id")


def test_verify_sql_syntax():
    """Verify the actual migration SQL for basic structural correctness."""
    import re
    migration_path = os.path.join(
        os.path.dirname(__file__), "..", "database", "migrations", "019_add_hypotheses.sql"
    )
    if not os.path.exists(migration_path):
        test("migration file exists", False, f"Not found at {migration_path}")
        return

    with open(migration_path) as f:
        sql = f.read()

    test("migration file has content", len(sql) > 0)
    test("migration has BEGIN", "BEGIN;" in sql or "BEGIN" in sql)
    test("migration has COMMIT", "COMMIT;" in sql or "COMMIT" in sql)

    # Count begin/commit
    begins = len(re.findall(r'\bBEGIN\b', sql))
    commits = len(re.findall(r'\bCOMMIT\b', sql))
    test("BEGIN/COMMIT balanced", begins == commits,
         f"BEGIN={begins}, COMMIT={commits}")

    test("migration has CREATE TABLE IF NOT EXISTS",
         "CREATE TABLE IF NOT EXISTS hypotheses" in sql)
    test("migration has UUID PK",
         "id UUID PRIMARY KEY" in sql)
    test("migration has engagement_id FK",
         "REFERENCES engagements(id)" in sql)
    test("migration has CASCADE delete",
         "ON DELETE CASCADE" in sql)
    test("migration has CHECK constraint on status",
         "CHECK (status IN" in sql)
    test("migration has CHECK constraint on confidence",
         "CHECK (confidence >=" in sql)
    test("migration has JSONB columns",
         "JSONB" in sql)
    test("migration has unique index on engagement+root_cause",
         "idx_hypotheses_engagement_root_cause" in sql)
    test("migration has unique index on engagement+source_finding",
         "idx_hypotheses_engagement_source_finding" in sql)
    test("migration has index on engagement_id",
         "idx_hypotheses_engagement_id" in sql)
    test("migration has index on status",
         "idx_hypotheses_status" in sql)


def test_allowed_table_name():
    """Verify hypotheses is in the BaseRepository allowed table names."""
    from database.repositories.base import _ALLOWED_TABLE_NAMES
    test("hypotheses in ALLOWED_TABLE_NAMES",
         "hypotheses" in _ALLOWED_TABLE_NAMES)


# ── Run all tests ──────────────────────────────────────────────────────

def run_all():
    global passed, failed
    passed = 0
    failed = 0

    print("=" * 60)
    print("HypothesisRepository Verification Tests (Mock-based)")
    print("=" * 60)
    print()

    tests = [
        ("Repository Properties", test_repository_properties),
        ("Allowed Table Names", test_allowed_table_name),
        ("Create", test_create),
        ("Create — ON CONFLICT returns existing", test_create_conflict_returns_existing),
        ("Create — ON CONFLICT SQL structure", test_create_on_conflict_sql),
        ("Get By Engagement", test_get_by_engagement),
        ("Get By Engagement — empty", test_get_by_engagement_empty),
        ("Update", test_update),
        ("Update — JSONB fields", test_update_jsonb),
        ("Update — nonexistent ID", test_update_nonexistent),
        ("Update — invalid column", test_update_invalid_column),
        ("Update — empty updates", test_update_empty_updates),
        ("Delete By Engagement", test_delete_by_engagement),
        ("Delete By Engagement — nonexistent", test_delete_by_engagement_nonexistent),
        ("Migration SQL Syntax", test_verify_sql_syntax),
    ]

    for name, test_fn in tests:
        print(f"\n[{name}]")
        try:
            test_fn()
        except Exception as e:
            _increment_failed()
            print(f"  [ERROR] {name} raised exception: {e}")

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


def _increment_failed():
    global failed
    failed += 1


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
