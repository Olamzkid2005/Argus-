"""Tests for EngagementRepository"""

from unittest.mock import MagicMock, patch

import pytest

from database.repositories.engagement_repository import EngagementRepository


@pytest.fixture
def repo():
    return EngagementRepository()


@pytest.fixture
def mock_db(repo):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [
        ("id",),
        ("org_id",),
        ("target_url",),
        ("status",),
        ("created_by",),
        ("created_at",),
    ]
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = (mock_conn, mock_cursor)

    with patch.object(repo, "db_operation", return_value=mock_cm):
        yield mock_cursor


class TestCreate:
    """Tests for EngagementRepository.create()."""

    def test_create_inserts_and_returns_engagement_dict(self, repo, mock_db):
        """create inserts a row with RETURNING * and returns the dict."""
        mock_db.fetchone.return_value = {
            "id": "eng-123",
            "org_id": "org-1",
            "target_url": "https://example.com",
            "authorization_proof": None,
            "authorized_scope": {},
            "status": "created",
            "created_by": "user-1",
        }

        result = repo.create(
            {
                "org_id": "org-1",
                "target_url": "https://example.com",
                "created_by": "user-1",
            }
        )

        assert result["org_id"] == "org-1"
        assert result["status"] == "created"
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO engagements" in sql
        assert "RETURNING *" in sql
        params = mock_db.execute.call_args[0][1]
        assert params[1] == "org-1"
        assert params[2] == "https://example.com"
        assert params[5] == "created"

    def test_create_uses_authorization_fallback(self, repo, mock_db):
        """create falls back from authorization_proof to authorization."""
        mock_db.fetchone.return_value = {
            "id": "eng-456",
            "authorization_proof": "proof123",
        }

        result = repo.create(
            {
                "org_id": "org-1",
                "target_url": "https://example.com",
                "authorization": "proof123",
                "created_by": "user-1",
            }
        )

        assert result["authorization_proof"] == "proof123"


class TestFindByOrg:
    """Tests for EngagementRepository.find_by_org()."""

    def test_find_by_org_returns_paginated_results_with_joins(self, repo, mock_db):
        """find_by_org uses LEFT JOINs for created_by_email and findings_count."""
        mock_db.fetchall.return_value = [
            {
                "id": "eng-1",
                "org_id": "org-1",
                "created_by_email": "admin@example.com",
                "findings_count": 3,
            },
        ]

        results = repo.find_by_org(org_id="org-1")

        assert len(results) == 1
        assert results[0]["created_by_email"] == "admin@example.com"
        assert results[0]["findings_count"] == 3
        sql = mock_db.execute.call_args[0][0]
        assert "LEFT JOIN users" in sql
        assert "findings" in sql

    def test_find_by_org_respects_limit_offset(self, repo, mock_db):
        """find_by_org passes limit and offset params."""
        mock_db.fetchall.return_value = []

        results = repo.find_by_org(org_id="org-1", limit=10, offset=20)

        assert results == []
        params = mock_db.execute.call_args[0][1]
        assert params[0] == "org-1"
        assert params[1] == 10
        assert params[2] == 20

    def test_find_by_org_returns_empty_list_when_no_results(self, repo, mock_db):
        """find_by_org returns [] when no engagements for org."""
        mock_db.fetchall.return_value = []
        results = repo.find_by_org(org_id="org-nonexistent")
        assert results == []


class TestFindActiveByOrg:
    """Tests for EngagementRepository.find_active_by_org()."""

    def test_find_active_by_org_filters_out_complete_failed(self, repo, mock_db):
        """find_active_by_org excludes statuses 'complete' and 'failed'."""
        mock_db.fetchall.return_value = [
            {"id": "eng-1", "org_id": "org-1", "status": "running"},
            {"id": "eng-2", "org_id": "org-1", "status": "in_progress"},
        ]

        results = repo.find_active_by_org(org_id="org-1")

        assert len(results) == 2
        sql = mock_db.execute.call_args[0][0]
        assert "NOT IN ('complete', 'failed')" in sql

    def test_find_active_by_org_returns_empty_when_all_inactive(self, repo, mock_db):
        """find_active_by_org returns [] when all engagements are complete/failed."""
        mock_db.fetchall.return_value = []
        results = repo.find_active_by_org(org_id="org-1")
        assert results == []


class TestUpdateStatus:
    """Tests for EngagementRepository.update_status()."""

    def test_update_status_delegates_to_update_by_id(self, repo):
        """update_status calls update_by_id with the engagement id and status."""
        with patch.object(
            repo, "update_by_id", return_value={"id": "eng-1", "status": "running"}
        ) as mock_update:
            result = repo.update_status(engagement_id="eng-1", status="running")

        mock_update.assert_called_once_with("eng-1", {"status": "running"})
        assert result["status"] == "running"


class TestFindByStatus:
    """Tests for EngagementRepository.find_by_status()."""

    def test_find_by_status_filters_by_status_and_org_id(self, repo, mock_db):
        """find_by_status filters by status and org_id (cross-org safety)."""
        mock_db.fetchall.return_value = [
            {"id": "eng-1", "org_id": "org-1", "status": "running"},
        ]

        results = repo.find_by_status(status="running", org_id="org-1")

        assert len(results) == 1
        sql = mock_db.execute.call_args[0][0]
        assert "status = %s" in sql
        assert "org_id = %s" in sql
        params = mock_db.execute.call_args[0][1]
        assert params[0] == "running"
        assert params[1] == "org-1"

    def test_find_by_status_respects_pagination(self, repo, mock_db):
        """find_by_status passes limit and offset params."""
        mock_db.fetchall.return_value = []

        results = repo.find_by_status(
            status="running", org_id="org-1", limit=5, offset=10
        )

        assert results == []
        params = mock_db.execute.call_args[0][1]
        assert params[0] == "running"
        assert params[1] == "org-1"
        assert params[2] == 5
        assert params[3] == 10

    def test_find_by_status_returns_empty_list_when_no_matches(self, repo, mock_db):
        """find_by_status returns [] when no engagements match."""
        mock_db.fetchall.return_value = []
        results = repo.find_by_status(status="nonexistent", org_id="org-1")
        assert results == []
