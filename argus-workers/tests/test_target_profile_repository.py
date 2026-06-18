"""Smoke tests for database/repositories/target_profile_repository.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for database.repositories.target_profile_repository."""

    def test_module_imports(self):
        """Verify target_profile_repository.py imports cleanly."""
        mod = importlib.import_module("database.repositories.target_profile_repository")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class TargetProfileRepository is available."""
        mod = importlib.import_module("database.repositories.target_profile_repository")
        assert hasattr(mod, "TargetProfileRepository")
        assert callable(mod.TargetProfileRepository)
