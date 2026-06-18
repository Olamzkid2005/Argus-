"""Smoke tests for parsers/parsers/testssl.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.testssl."""

    def test_module_imports(self):
        """Verify testssl.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.testssl")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class TestsslParser is available."""
        mod = importlib.import_module("parsers.parsers.testssl")
        assert hasattr(mod, "TestsslParser")
        assert callable(mod.TestsslParser)
