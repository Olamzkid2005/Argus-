"""Smoke tests for tasks/self_scan.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.self_scan."""

    def test_module_imports(self):
        """Verify self_scan.py imports cleanly."""
        mod = importlib.import_module("tasks.self_scan")
        assert mod is not None

    def test_function_run_self_scan_exists(self):
        """Verify function run_self_scan is exported."""
        mod = importlib.import_module("tasks.self_scan")
        assert hasattr(mod, "run_self_scan")
        assert callable(mod.run_self_scan)
