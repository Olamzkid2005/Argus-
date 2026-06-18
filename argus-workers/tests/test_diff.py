"""Smoke tests for tasks/diff.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.diff."""

    def test_module_imports(self):
        """Verify diff.py imports cleanly."""
        mod = importlib.import_module("tasks.diff")
        assert mod is not None

    def test_function_run_scan_diff_exists(self):
        """Verify function run_scan_diff is exported."""
        mod = importlib.import_module("tasks.diff")
        assert hasattr(mod, "run_scan_diff")
        assert callable(mod.run_scan_diff)
