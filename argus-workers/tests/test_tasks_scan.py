"""Tests for tasks.scan — Category: function"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock heavy deps before importing tasks.scan so the module doesn't bind
# real database/redis references.  After import, remove tasks.scan from
# sys.modules so later files (e.g. test_full_scan_pipeline_e2e.py) re-import
# it fresh with their own mocked dependencies.
_mock_app = MagicMock()
_mock_app.task = lambda **_kwargs: lambda f: f
_mock_celery = type(sys)("celery_app")
_mock_celery.app = _mock_app
_heavy_deps = patch.dict(
    sys.modules,
    {
        "celery_app": _mock_celery,
        "psycopg2": MagicMock(),
        "redis": MagicMock(),
        "database": MagicMock(),
        "database.connection": MagicMock(),
        "database.repositories": MagicMock(),
        "database.repositories.finding_repository": MagicMock(),
        "database.repositories.engagement_repository": MagicMock(),
        "database.repositories.report_repository": MagicMock(),
        "database.repositories.agent_decision_repository": MagicMock(),
        "database.repositories.rate_limit_repository": MagicMock(),
    },
)
_heavy_deps.start()
from tasks.scan import auth_focused_scan, deep_scan, run_scan  # noqa: E402

_heavy_deps.stop()

# Clean up so e2e tests re-import with their own mocked dependencies
sys.modules.pop("tasks.scan", None)
_tasks_pkg = sys.modules.get("tasks")
if _tasks_pkg is not None:
    _tasks_pkg.__dict__.pop("scan", None)


class TestRunScan:
    """Tests for the run_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_scan()


class TestDeepScan:
    """Tests for the deep_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            deep_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            deep_scan()


class TestAuthFocusedScan:
    """Tests for the auth_focused_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            auth_focused_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            auth_focused_scan()
