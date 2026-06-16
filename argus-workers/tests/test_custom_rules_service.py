"""Tests for custom_rules_service.py

Covers:
  - load() with no engagement returns empty list
  - load() returns engagement-specific rules
  - load() falls back to org-level rules
  - load() handles DB exceptions gracefully
  - publish() loads rules and publishes via ws_publisher
  - publish() with no rules does nothing
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestCustomRulesServiceLoad:
    """Tests for the static load() method."""

    @pytest.fixture
    def mock_cursor(self):
        with patch("database.connection.db_cursor") as mock_db:
            cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = cursor
            yield cursor

    def test_no_engagement_row_returns_empty(self, mock_cursor):
        from orchestrator_pkg.custom_rules.custom_rules_service import (
            CustomRulesService,
        )

        mock_cursor.fetchone.return_value = None
        result = CustomRulesService.load("eng-nonexistent")
        assert result == []
        mock_cursor.execute.assert_called_once_with(
            "SELECT org_id FROM engagements WHERE id = %s",
            ("eng-nonexistent",),
        )

    def test_returns_engagement_specific_rules(self, mock_cursor):
        from orchestrator_pkg.custom_rules.custom_rules_service import (
            CustomRulesService,
        )

        mock_cursor.fetchone.return_value = ("org-42",)
        mock_cursor.description = [
            ("id", None), ("name", None), ("description", None),
            ("severity", None), ("category", None), ("rule_yaml", None),
            ("tags", None),
        ]
        mock_cursor.fetchall.side_effect = [
            [("rule-1", "Test Rule", "A test rule", "HIGH", "injection",
              "yaml_content", ["tag1"])],
            [],
        ]

        result = CustomRulesService.load("eng-001")

        assert len(result) == 1
        assert result[0]["id"] == "rule-1"
        assert result[0]["name"] == "Test Rule"
        assert result[0]["severity"] == "HIGH"

    def test_falls_back_to_org_rules(self, mock_cursor):
        from orchestrator_pkg.custom_rules.custom_rules_service import (
            CustomRulesService,
        )

        mock_cursor.fetchone.return_value = ("org-42",)
        mock_cursor.description = [
            ("id", None), ("name", None), ("description", None),
            ("severity", None), ("category", None), ("rule_yaml", None),
            ("tags", None),
        ]
        mock_cursor.fetchall.side_effect = [
            [],
            [("org-rule-1", "Org Rule", "Org level rule", "MEDIUM",
              "config", "yaml", [])],
        ]

        result = CustomRulesService.load("eng-002")

        assert len(result) == 1
        assert result[0]["id"] == "org-rule-1"

    def test_handles_db_exception_gracefully(self):
        from orchestrator_pkg.custom_rules.custom_rules_service import (
            CustomRulesService,
        )

        with patch("database.connection.db_cursor") as mock_db:
            mock_db.return_value.__enter__.side_effect = Exception("DB error")
            result = CustomRulesService.load("eng-001")
            assert result == []


class TestCustomRulesServicePublish:
    """Tests for the static publish() method."""

    def test_publishes_rules(self):
        from orchestrator_pkg.custom_rules.custom_rules_service import (
            CustomRulesService,
        )

        with patch.object(CustomRulesService, "load", return_value=[
            {"name": "Rule 1", "severity": "HIGH", "description": "Desc 1"},
            {"name": "Rule 2", "severity": "MEDIUM", "description": "Desc 2"},
        ]):
            ws_publisher = MagicMock()
            CustomRulesService.publish(
                engagement_id="eng-001",
                targets=["https://example.com"],
                ws_publisher=ws_publisher,
            )

            assert ws_publisher.publish_scanner_activity.call_count == 2

    def test_no_rules_does_nothing(self):
        from orchestrator_pkg.custom_rules.custom_rules_service import (
            CustomRulesService,
        )

        with patch.object(CustomRulesService, "load", return_value=[]):
            ws_publisher = MagicMock()
            CustomRulesService.publish(
                engagement_id="eng-001",
                targets=["https://example.com"],
                ws_publisher=ws_publisher,
            )

            ws_publisher.publish_scanner_activity.assert_not_called()
