"""Smoke tests for parsers/parsers/gau.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.gau."""

    def test_module_imports(self):
        """Verify gau.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.gau")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class GauParser is available."""
        mod = importlib.import_module("parsers.parsers.gau")
        assert hasattr(mod, "GauParser")
        assert callable(mod.GauParser)
