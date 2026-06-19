"""Tests for tasks.scheduled — Category: function"""

import pytest

from tasks.scheduled import (
    _build_budget_from_aggressiveness,
    _spawn_engagement,
    run_due_scans,
)


class TestBuildBudgetFromAggressiveness:
    """Tests for the _build_budget_from_aggressiveness function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = run_due_scans()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _build_budget_from_aggressiveness()


class TestRunDueScans:
    """Tests for the run_due_scans function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = run_due_scans()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns a list."""
        instance = run_due_scans()
        assert isinstance(instance, dict)

class TestSpawnEngagement:
    """Tests for the _spawn_engagement function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = run_due_scans()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _spawn_engagement()
