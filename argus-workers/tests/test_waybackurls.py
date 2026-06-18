"""Smoke tests for parsers/parsers/waybackurls.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.waybackurls."""

    def test_module_imports(self):
        """Verify waybackurls.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.waybackurls")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class WaybackurlsParser is available."""
        mod = importlib.import_module("parsers.parsers.waybackurls")
        assert hasattr(mod, "WaybackurlsParser")
        assert callable(mod.WaybackurlsParser)
