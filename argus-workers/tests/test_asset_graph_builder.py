"""Smoke tests for tools/attack_paths/asset_graph_builder.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_paths.asset_graph_builder."""

    def test_module_imports(self):
        """Verify asset_graph_builder.py imports cleanly."""
        mod = importlib.import_module("tools.attack_paths.asset_graph_builder")
        assert mod is not None

    def test_function_build_asset_graph_exists(self):
        """Verify function build_asset_graph is exported."""
        mod = importlib.import_module("tools.attack_paths.asset_graph_builder")
        assert hasattr(mod, "build_asset_graph")
        assert callable(mod.build_asset_graph)
