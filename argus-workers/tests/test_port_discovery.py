"""Smoke tests for tools/attack_surface/port_discovery.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_surface.port_discovery."""

    def test_module_imports(self):
        """Verify port_discovery.py imports cleanly."""
        mod = importlib.import_module("tools.attack_surface.port_discovery")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class PortDiscovery is available."""
        mod = importlib.import_module("tools.attack_surface.port_discovery")
        assert hasattr(mod, "PortDiscovery")
        assert callable(mod.PortDiscovery)
