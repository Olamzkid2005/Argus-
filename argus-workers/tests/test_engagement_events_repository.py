"""Tests for EngagementEventsRepository"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from database.repositories.engagement_events_repository import (
    EngagementEventsRepository,
)


@pytest.fixture
def repo():
    return EngagementEventsRepository()


@pytest.fixture
def mock_db(repo):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [
        ("id",),
        ("engagement_id",),
        ("event_type",),
        ("event_data",),
        ("actor",),
        ("created_at",),
    ]
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = (mock_conn, mock_cursor)

    with patch.object(repo, "db_operation", return_value=mock_cm):
        yield mock_cursor


class TestRecordEvent:
    """Tests for EngagementEventsRepository.record_event()."""

    def test_record_event_inserts_and_returns_uuid_string(self, repo, mock_db):
        """record_event inserts a row and returns a valid UUID string."""
        event_id = repo.record_event(
            engagement_id="eng-123",
            event_type="scan_started",
            event_data={"tool": "nuclei"},
            actor="system",
        )

        assert isinstance(event_id, str)
        uuid.UUID(event_id)

        mock_db.execute.assert_called_once()
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO engagement_events" in sql

        params = mock_db.execute.call_args[0][1]
        assert params[1] == "eng-123"
        assert params[2] == "scan_started"
        assert params[4] == "system"

    def test_record_event_defaults_event_data_to_empty_dict(self, repo, mock_db):
        """record_event uses {} when event_data is None."""
        repo.record_event(
            engagement_id="eng-123",
            event_type="status_changed",
            actor=None,
        )

        params = mock_db.execute.call_args[0][1]
        assert params[3] is not None


class TestGetEvents:
    """Tests for EngagementEventsRepository.get_events()."""

    def test_get_events_returns_all_events(self, repo, mock_db):
        """get_events returns all events for an engagement."""
        mock_db.fetchall.return_value = [
            {"id": "1", "engagement_id": "eng-123", "event_type": "scan_started"},
            {"id": "2", "engagement_id": "eng-123", "event_type": "scan_completed"},
        ]

        results = repo.get_events(engagement_id="eng-123")

        assert len(results) == 2
        assert results[0]["event_type"] == "scan_started"
        assert results[1]["event_type"] == "scan_completed"

    def test_get_events_filters_by_event_type(self, repo, mock_db):
        """get_events applies event_type filter when provided."""
        mock_db.fetchall.return_value = [
            {"id": "1", "engagement_id": "eng-123", "event_type": "scan_started"},
        ]

        results = repo.get_events(engagement_id="eng-123", event_type="scan_started")

        assert len(results) == 1
        assert results[0]["event_type"] == "scan_started"
        sql = mock_db.execute.call_args[0][0]
        assert "event_type = %s" in sql

    def test_get_events_returns_empty_list_when_no_events(self, repo, mock_db):
        """get_events returns [] when no events found."""
        mock_db.fetchall.return_value = []
        results = repo.get_events(engagement_id="eng-999")
        assert results == []


class TestGetEventTimeline:
    """Tests for EngagementEventsRepository.get_event_timeline()."""

    def test_get_event_timeline_returns_chronological_order(self, repo, mock_db):
        """get_event_timeline orders by created_at ASC."""
        mock_db.fetchall.return_value = [
            {"id": "1", "engagement_id": "eng-123", "event_type": "scan_started"},
        ]

        results = repo.get_event_timeline(engagement_id="eng-123")

        assert len(results) == 1
        sql = mock_db.execute.call_args[0][0]
        assert "ORDER BY created_at ASC" in sql

    def test_get_event_timeline_respects_limit_offset(self, repo, mock_db):
        """get_event_timeline passes limit and offset params."""
        mock_db.fetchall.return_value = []

        results = repo.get_event_timeline(engagement_id="eng-123", limit=5, offset=10)

        assert results == []
        params = mock_db.execute.call_args[0][1]
        assert params[0] == "eng-123"
        assert params[1] == 5
        assert params[2] == 10
