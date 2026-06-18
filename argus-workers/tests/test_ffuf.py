"""Smoke tests for parsers/parsers/ffuf.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.ffuf."""

    def test_module_imports(self):
        """Verify ffuf.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.ffuf")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class FfufParser is available."""
        mod = importlib.import_module("parsers.parsers.ffuf")
        assert hasattr(mod, "FfufParser")
        assert callable(mod.FfufParser)
