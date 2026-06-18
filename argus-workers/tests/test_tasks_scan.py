"""Smoke tests for tasks/scan.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.scan."""

    def test_module_imports(self):
        """Verify scan.py imports cleanly."""
        mod = importlib.import_module("tasks.scan")
        assert mod is not None

    def test_function_run_scan_exists(self):
        """Verify function run_scan is exported."""
        mod = importlib.import_module("tasks.scan")
        assert hasattr(mod, "run_scan")
        assert callable(mod.run_scan)

    def test_function_deep_scan_exists(self):
        """Verify function deep_scan is exported."""
        mod = importlib.import_module("tasks.scan")
        assert hasattr(mod, "deep_scan")
        assert callable(mod.deep_scan)

    def test_function_auth_focused_scan_exists(self):
        """Verify function auth_focused_scan is exported."""
        mod = importlib.import_module("tasks.scan")
        assert hasattr(mod, "auth_focused_scan")
        assert callable(mod.auth_focused_scan)
