"""Smoke tests for parsers/parsers/base.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.base."""

    def test_module_imports(self):
        """Verify base.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.base")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ParserError is available."""
        mod = importlib.import_module("parsers.parsers.base")
        assert hasattr(mod, "ParserError")
        assert callable(mod.ParserError)
