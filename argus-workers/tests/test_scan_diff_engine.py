"""Smoke tests for scan_diff_engine.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for scan_diff_engine."""

    def test_module_imports(self):
        """Verify scan_diff_engine.py imports cleanly."""
        mod = importlib.import_module("scan_diff_engine")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ScanDiffEngine is available."""
        mod = importlib.import_module("scan_diff_engine")
        assert hasattr(mod, "ScanDiffEngine")
        assert callable(mod.ScanDiffEngine)
