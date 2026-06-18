"""Smoke tests for database/repositories/finding_repository.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for database.repositories.finding_repository."""

    def test_module_imports(self):
        """Verify finding_repository.py imports cleanly."""
        mod = importlib.import_module("database.repositories.finding_repository")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class FindingCapExceededError is available."""
        mod = importlib.import_module("database.repositories.finding_repository")
        assert hasattr(mod, "FindingCapExceededError")
        assert callable(mod.FindingCapExceededError)
