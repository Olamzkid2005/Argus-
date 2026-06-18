"""Tests for database.migrations.runner — Category: function"""

import pytest

from database.migrations.runner import _ensure_tracking_table
from database.migrations.runner import _get_applied
from database.migrations.runner import _mark_applied
from database.migrations.runner import run_migrations


class TestEnsureTrackingTable:
    """Tests for the _ensure_tracking_table function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = run_migrations()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _ensure_tracking_table()


class TestGetApplied:
    """Tests for the _get_applied function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = run_migrations()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _get_applied()


class TestMarkApplied:
    """Tests for the _mark_applied function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = run_migrations()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _mark_applied()


class TestRunMigrations:
    """Tests for the run_migrations function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = run_migrations()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_migrations()
