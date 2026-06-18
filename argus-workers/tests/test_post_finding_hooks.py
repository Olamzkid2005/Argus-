"""Tests for post_finding_hooks.py

Covers:
  - fire_finding_webhooks severity filtering
  - fire_finding_webhooks without engagement_id
  - _get_matching_webhooks
  - _dispatch success/failure
  - _mark_triggered
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from post_finding_hooks import (
    _dispatch,
    _get_matching_webhooks,
    _mark_triggered,
    fire_finding_webhooks,
)


class TestFireFindingWebhooks:
    """Tests for fire_finding_webhooks."""

    def test_skips_low_severity(self):
        result = fire_finding_webhooks(
            {
                "id": "finding-1",
                "engagement_id": "eng-001",
                "severity": "LOW",
                "type": "XSS",
            }
        )
        assert result is None  # No webhooks fired for LOW severity

    def test_fires_for_critical(self):
        with patch(
            "post_finding_hooks._get_matching_webhooks", return_value=[]
        ) as mock_get:
            fire_finding_webhooks(
                {
                    "id": "finding-1",
                    "engagement_id": "eng-001",
                    "severity": "CRITICAL",
                    "type": "SQL_INJECTION",
                    "endpoint": "/api",
                    "source_tool": "nuclei",
                    "confidence": 0.9,
                }
            )
            mock_get.assert_called_once_with("eng-001")

    def test_skips_without_engagement_id(self):
        fire_finding_webhooks(
            {
                "id": "finding-1",
                "severity": "CRITICAL",
            }
        )  # Should return without error

    def test_fires_webhooks(self):
        with (
            patch(
                "post_finding_hooks._get_matching_webhooks",
                return_value=[
                    {"id": "wh-1", "webhook_url": "https://hooks.example.com"}
                ],
            ),
            patch("post_finding_hooks._dispatch") as mock_dispatch,
        ):
            fire_finding_webhooks(
                {
                    "id": "finding-1",
                    "engagement_id": "eng-001",
                    "severity": "HIGH",
                    "type": "XSS",
                    "endpoint": "/search",
                }
            )
            mock_dispatch.assert_called_once()


class TestGetMatchingWebhooks:
    """Tests for _get_matching_webhooks."""

    def test_db_error_returns_empty(self):
        mock_db = MagicMock()
        mock_db.get_connection.side_effect = Exception("DB error")
        with patch("database.connection.get_db", return_value=mock_db):
            result = _get_matching_webhooks("eng-001")
            assert result == []


class TestDispatch:
    """Tests for _dispatch."""

    def test_successful_dispatch(self):
        class FakeResponse:
            status_code = 200

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def post(self, url, json=None):
                return FakeResponse()

        with (
            patch("post_finding_hooks.httpx.Client", return_value=FakeClient()),
            patch("post_finding_hooks._mark_triggered") as mock_mark,
        ):
            _dispatch("https://hooks.example.com", {"event": "test"}, "wh-1")
            mock_mark.assert_called_once_with("wh-1", success=True)

    def test_failed_dispatch(self):
        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def post(self, url, json=None):
                raise Exception("Connection error")

        with (
            patch("post_finding_hooks.httpx.Client", return_value=FakeClient()),
            patch("post_finding_hooks._mark_triggered") as mock_mark,
        ):
            _dispatch("https://hooks.example.com", {"event": "test"}, "wh-1")
            mock_mark.assert_called_once_with("wh-1", success=False)


class TestMarkTriggered:
    """Tests for _mark_triggered."""

    def test_successful_update(self):
        mock_db = MagicMock()
        with patch("database.connection.get_db", return_value=mock_db):
            _mark_triggered("wh-1", success=True)
            # Should not raise

    def test_db_error(self):
        mock_db = MagicMock()
        mock_db.get_connection.side_effect = Exception("DB error")
        with patch("database.connection.get_db", return_value=mock_db):
            _mark_triggered("wh-1", success=True)
            # Should not raise
