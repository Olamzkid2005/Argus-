"""Tests for the signal-driven scan dispatch helpers in tasks.scan.

Covers:
- _detect_high_value_endpoints (CRITICAL/HIGH findings warrant deepening)
- _detect_auth_endpoints (login/auth surface warrants auth-focused scan)
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
# Start → import → stop: the tasks module binds the mock app at import time,
# but stopping the patch restores the REAL celery_app in sys.modules so other
# test files (e.g. test_full_scan_pipeline_e2e.py, which reads app.conf.task_routes
# at test time) are not polluted for the whole session.
_heavy_deps = patch.dict(sys.modules, {"celery_app": _mock_celery})
_heavy_deps.start()
from tasks.scan import (  # noqa: E402
    _check_missing_phase_tools,
    _detect_auth_endpoints,
    _detect_high_value_endpoints,
)

_heavy_deps.stop()
# Remove the contaminated tasks.scan module from sys.modules so that later
# test files (e.g. test_full_scan_pipeline_e2e.py) re-import it fresh with
# the real celery_app.  Without this, tasks.scan stays cached with
# app = _mock_app (a plain lambda) and e2e tests see
# "'function' object has no attribute 'run'".
sys.modules.pop("tasks.scan", None)
import tasks as _tasks_pkg  # noqa: E402

_tasks_pkg.__dict__.pop("scan", None)


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


class TestDetectAuthEndpoints:
    """_detect_auth_endpoints: signal-driven auth-focused scan trigger."""

    def test_returns_auth_endpoints_when_present(self):
        recon = MagicMock()
        recon.has_login_page = True
        recon.auth_endpoints = ["https://x/login", "https://x/api/auth"]
        recon.live_endpoints = ["https://x/"]
        with patch("tasks.utils.load_recon_context", return_value=recon):
            assert _detect_auth_endpoints("eng-1") == [
                "https://x/login",
                "https://x/api/auth",
            ]

    def test_falls_back_to_live_endpoints_when_login_page_only(self):
        """has_login_page=True but no extracted auth URLs → use live endpoints."""
        recon = MagicMock()
        recon.has_login_page = True
        recon.auth_endpoints = []
        recon.live_endpoints = ["https://x/", "https://x/admin"]
        with patch("tasks.utils.load_recon_context", return_value=recon):
            assert _detect_auth_endpoints("eng-1") == [
                "https://x/",
                "https://x/admin",
            ]

    def test_returns_empty_without_auth_surface(self):
        recon = MagicMock()
        recon.has_login_page = False
        recon.auth_endpoints = []
        with patch("tasks.utils.load_recon_context", return_value=recon):
            assert _detect_auth_endpoints("eng-1") == []

    def test_returns_empty_without_recon_context(self):
        with patch("tasks.utils.load_recon_context", return_value=None):
            assert _detect_auth_endpoints("eng-1") == []

    def test_load_failure_is_non_fatal(self):
        with patch(
            "tasks.utils.load_recon_context", side_effect=Exception("redis down")
        ):
            assert _detect_auth_endpoints("eng-1") == []

    def test_dedupes_and_caps(self):
        recon = MagicMock()
        recon.has_login_page = True
        recon.auth_endpoints = [
            "https://x/login",
            "https://x/login",
            "",
            "https://x/auth2",
            "https://x/auth3",
            "https://x/auth4",
            "https://x/auth5",
            "https://x/auth6",
        ]
        with patch("tasks.utils.load_recon_context", return_value=recon):
            endpoints = _detect_auth_endpoints("eng-1", max_endpoints=5)
        assert len(endpoints) == 5
        assert endpoints.count("https://x/login") == 1


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
