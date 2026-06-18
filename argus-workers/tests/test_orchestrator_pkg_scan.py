"""Smoke tests for orchestrator_pkg/scan.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for orchestrator_pkg.scan."""

    def test_module_imports(self):
        """Verify scan.py imports cleanly."""
        mod = importlib.import_module("orchestrator_pkg.scan")
        assert mod is not None

    def test_function_execute_scan_tools_exists(self):
        """Verify function execute_scan_tools is exported."""
        mod = importlib.import_module("orchestrator_pkg.scan")
        assert hasattr(mod, "execute_scan_tools")
        assert callable(mod.execute_scan_tools)
