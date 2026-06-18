"""Smoke tests for tools/attack_paths/path_finder.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_paths.path_finder."""

    def test_module_imports(self):
        """Verify path_finder.py imports cleanly."""
        mod = importlib.import_module("tools.attack_paths.path_finder")
        assert mod is not None

    def test_function_find_paths_exists(self):
        """Verify function find_paths is exported."""
        mod = importlib.import_module("tools.attack_paths.path_finder")
        assert hasattr(mod, "find_paths")
        assert callable(mod.find_paths)
