"""Smoke tests for tools/attack_surface/asset_graph.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_surface.asset_graph."""

    def test_module_imports(self):
        """Verify asset_graph.py imports cleanly."""
        mod = importlib.import_module("tools.attack_surface.asset_graph")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class Asset is available."""
        mod = importlib.import_module("tools.attack_surface.asset_graph")
        assert hasattr(mod, "Asset")
        assert callable(mod.Asset)
