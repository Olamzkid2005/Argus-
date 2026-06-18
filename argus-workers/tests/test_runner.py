"""Smoke tests for database/migrations/runner.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for database.migrations.runner."""

    def test_module_imports(self):
        """Verify runner.py imports cleanly."""
        mod = importlib.import_module("database.migrations.runner")
        assert mod is not None

    def test_function_run_migrations_exists(self):
        """Verify function run_migrations is exported."""
        mod = importlib.import_module("database.migrations.runner")
        assert hasattr(mod, "run_migrations")
        assert callable(mod.run_migrations)
