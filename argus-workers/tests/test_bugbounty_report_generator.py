"""Smoke tests for tools/bugbounty_report_generator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.bugbounty_report_generator."""

    def test_module_imports(self):
        """Verify bugbounty_report_generator.py imports cleanly."""
        mod = importlib.import_module("tools.bugbounty_report_generator")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ArgusFindingAdapter is available."""
        mod = importlib.import_module("tools.bugbounty_report_generator")
        assert hasattr(mod, "ArgusFindingAdapter")
        assert callable(mod.ArgusFindingAdapter)
