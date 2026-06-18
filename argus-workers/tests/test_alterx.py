"""Smoke tests for parsers/parsers/alterx.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.alterx."""

    def test_module_imports(self):
        """Verify alterx.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.alterx")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AlterxParser is available."""
        mod = importlib.import_module("parsers.parsers.alterx")
        assert hasattr(mod, "AlterxParser")
        assert callable(mod.AlterxParser)
