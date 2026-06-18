"""Smoke tests for parsers/parsers/wpscan.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.wpscan."""

    def test_module_imports(self):
        """Verify wpscan.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.wpscan")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class WpscanParser is available."""
        mod = importlib.import_module("parsers.parsers.wpscan")
        assert hasattr(mod, "WpscanParser")
        assert callable(mod.WpscanParser)
