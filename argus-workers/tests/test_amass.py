"""Smoke tests for parsers/parsers/amass.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.amass."""

    def test_module_imports(self):
        """Verify amass.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.amass")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AmassParser is available."""
        mod = importlib.import_module("parsers.parsers.amass")
        assert hasattr(mod, "AmassParser")
        assert callable(mod.AmassParser)
