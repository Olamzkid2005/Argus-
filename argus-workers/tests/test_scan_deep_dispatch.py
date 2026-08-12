"""Tests for the signal-driven deep-scan dispatch helpers in tasks.scan.

Covers:
- _detect_high_value_endpoints (CRITICAL/HIGH findings warrant deepening)
- _check_missing_phase_tools (operator-visible missing-binary warnings)
"""

import sys
from unittest.mock import MagicMock, patch

# Mock celery_app BEFORE importing tasks.scan — see test_fleet_pivot.py for the
# rationale (collection-order fragility with other files' celery mocks).
_mock_app = MagicMock()
_mock_app.task = lambda **_kwargs: lambda f: f
_mock_celery = type(sys)("celery_app")
_mock_celery.app = _mock_app
patch.dict(sys.modules, {"celery_app": _mock_celery}).start()

from tasks.scan import (  # noqa: E402
    _check_missing_phase_tools,
    _detect_high_value_endpoints,
)


class TestDetectHighValueEndpoints:
    def test_returns_empty_without_db(self):
        assert _detect_high_value_endpoints("eng-1", None) == []

    def test_returns_empty_when_no_findings(self):
        fake_repo = MagicMock()
        fake_repo.get_findings_by_engagement.return_value = ([], 0)
        with patch(
            "database.repositories.finding_repository.FindingRepository",
            return_value=fake_repo,
        ):
            assert _detect_high_value_endpoints("eng-1", "sqlite:///x") == []

    def test_returns_priority_endpoints_when_high_value(self):
        fake_repo = MagicMock()
        findings = [{"id": 1, "severity": "critical", "endpoint": "http://a"}]
        fake_repo.get_findings_by_engagement.return_value = (findings, 1)
        engine = MagicMock()
        engine.detect_high_value_targets.return_value = True
        engine.get_priority_endpoints.return_value = ["http://a"]
        with patch(
            "database.repositories.finding_repository.FindingRepository",
            return_value=fake_repo,
        ), patch("intelligence_engine.IntelligenceEngine", return_value=engine):
            assert _detect_high_value_endpoints("eng-1", "sqlite:///x") == ["http://a"]

    def test_returns_empty_when_not_high_value(self):
        fake_repo = MagicMock()
        fake_repo.get_findings_by_engagement.return_value = ([{"id": 1}], 1)
        engine = MagicMock()
        engine.detect_high_value_targets.return_value = False
        with patch(
            "database.repositories.finding_repository.FindingRepository",
            return_value=fake_repo,
        ), patch("intelligence_engine.IntelligenceEngine", return_value=engine):
            assert _detect_high_value_endpoints("eng-1", "sqlite:///x") == []


class TestCheckMissingPhaseTools:
    def test_returns_empty_when_all_available(self):
        registry = MagicMock()
        registry.is_available.return_value = True
        with patch("tool_core.registry.ToolRegistry", return_value=registry):
            assert _check_missing_phase_tools("scan") == []

    def test_lists_missing_tools(self):
        registry = MagicMock()
        registry.is_available.side_effect = lambda name: name == "nuclei"
        with patch("tool_core.registry.ToolRegistry", return_value=registry):
            missing = _check_missing_phase_tools("scan")
        assert missing
        assert "nuclei" not in missing  # available

    def test_tolerates_definition_load_failure(self):
        with patch(
            "tool_definitions.get_tools_for_phase", side_effect=Exception("boom")
        ):
            assert _check_missing_phase_tools("scan") == []
