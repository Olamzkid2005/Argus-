"""Tests for tasks.scheduled — Category: function"""


import os

import pytest

from tasks.scheduled import (
    _build_budget_from_aggressiveness,
    _spawn_engagement,
    run_due_scans,
)


class TestBuildBudgetFromAggressiveness:
    """Tests for the _build_budget_from_aggressiveness function."""

    def test_requires_aggressiveness(self):
        """Function requires an aggressiveness argument."""
        with pytest.raises(TypeError):
            _build_budget_from_aggressiveness()

    def test_basic_execution(self):
        """Function returns a budget dict for a valid aggressiveness value."""
        instance = _build_budget_from_aggressiveness("gentle")
        assert instance is not None
        assert isinstance(instance, dict)
        assert instance["max_cycles"] == 2
        assert instance["max_depth"] == 1


class TestSpawnEngagement:
    """Tests for the _spawn_engagement function."""

    def test_requires_arguments(self):
        """Function requires the scheduled-engagement creation arguments."""
        with pytest.raises(TypeError):
            _spawn_engagement()


class TestRunDueScans:
    """Tests for the run_due_scans Celery task."""

    def test_basic_execution_with_empty_database_url(self):
        """Without DATABASE_URL the task is a no-op and returns a status dict
        rather than connecting to the database."""
        previous = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = ""
            instance = run_due_scans()
            assert instance is not None
            assert isinstance(instance, dict)
            assert instance["status"] == "skipped"
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
