"""Smoke tests for parsers/parsers/subfinder.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.subfinder."""

    def test_module_imports(self):
        """Verify subfinder.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.subfinder")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class SubfinderParser is available."""
        mod = importlib.import_module("parsers.parsers.subfinder")
        assert hasattr(mod, "SubfinderParser")
        assert callable(mod.SubfinderParser)
