"""Smoke tests for tools/attack_surface/url_discovery.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_surface.url_discovery."""

    def test_module_imports(self):
        """Verify url_discovery.py imports cleanly."""
        mod = importlib.import_module("tools.attack_surface.url_discovery")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class URLDiscovery is available."""
        mod = importlib.import_module("tools.attack_surface.url_discovery")
        assert hasattr(mod, "URLDiscovery")
        assert callable(mod.URLDiscovery)
