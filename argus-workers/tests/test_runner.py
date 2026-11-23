"""Tests for database.migrations.runner — Category: function"""


import os

import pytest

from database.migrations.runner import (
    _ensure_tracking_table,
    _get_applied,
    _mark_applied,
    run_migrations,
)


class TestEnsureTrackingTable:
    """Tests for the _ensure_tracking_table function."""

    def test_requires_connection(self):
        """Function requires a connection argument."""
        with pytest.raises(TypeError):
            _ensure_tracking_table()


class TestGetApplied:
    """Tests for the _get_applied function."""

    def test_requires_connection(self):
        """Function requires a connection argument."""
        with pytest.raises(TypeError):
            _get_applied()


class TestMarkApplied:
    """Tests for the _mark_applied function."""

    def test_requires_connection_and_filename(self):
        """Function requires a connection and a filename argument."""
        with pytest.raises(TypeError):
            _mark_applied()


class TestRunMigrations:
    """Tests for the run_migrations function."""

    def test_basic_execution_with_empty_database_url(self):
        """With no DATABASE_URL the runner is a no-op and returns an empty
        list rather than connecting."""
        previous = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = ""
            instance = run_migrations()
            assert instance is not None
            assert isinstance(instance, list)
            assert instance == []
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
