"""Smoke tests for parsers/parsers/gospider.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.gospider."""

    def test_module_imports(self):
        """Verify gospider.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.gospider")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class GospiderParser is available."""
        mod = importlib.import_module("parsers.parsers.gospider")
        assert hasattr(mod, "GospiderParser")
        assert callable(mod.GospiderParser)
