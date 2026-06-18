"""Smoke tests for tools/correlation/root_cause.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.correlation.root_cause."""

    def test_module_imports(self):
        """Verify root_cause.py imports cleanly."""
        mod = importlib.import_module("tools.correlation.root_cause")
        assert mod is not None

    def test_function_group_by_root_cause_exists(self):
        """Verify function group_by_root_cause is exported."""
        mod = importlib.import_module("tools.correlation.root_cause")
        assert hasattr(mod, "group_by_root_cause")
        assert callable(mod.group_by_root_cause)

    def test_function_find_root_causes_exists(self):
        """Verify function find_root_causes is exported."""
        mod = importlib.import_module("tools.correlation.root_cause")
        assert hasattr(mod, "find_root_causes")
        assert callable(mod.find_root_causes)
