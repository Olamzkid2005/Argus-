"""Smoke tests for database/repositories/base.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for database.repositories.base."""

    def test_module_imports(self):
        """Verify base.py imports cleanly."""
        mod = importlib.import_module("database.repositories.base")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class BaseRepository is available."""
        mod = importlib.import_module("database.repositories.base")
        assert hasattr(mod, "BaseRepository")
        assert callable(mod.BaseRepository)

    def test_function_validate_columns_exists(self):
        """Verify function validate_columns is exported."""
        mod = importlib.import_module("database.repositories.base")
        assert hasattr(mod, "validate_columns")
        assert callable(mod.validate_columns)
