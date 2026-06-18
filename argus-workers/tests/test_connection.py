"""Smoke tests for database/connection.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for database.connection."""

    def test_module_imports(self):
        """Verify connection.py imports cleanly."""
        mod = importlib.import_module("database.connection")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class DatabaseConnectionError is available."""
        mod = importlib.import_module("database.connection")
        assert hasattr(mod, "DatabaseConnectionError")
        assert callable(mod.DatabaseConnectionError)
