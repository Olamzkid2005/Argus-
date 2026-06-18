"""Smoke tests for runtime/shadow_mode.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for runtime.shadow_mode."""

    def test_module_imports(self):
        """Verify shadow_mode.py imports cleanly."""
        mod = importlib.import_module("runtime.shadow_mode")
        assert mod is not None

    def test_function_shadow_compare_exists(self):
        """Verify function shadow_compare is exported."""
        mod = importlib.import_module("runtime.shadow_mode")
        assert hasattr(mod, "shadow_compare")
        assert callable(mod.shadow_compare)

    def test_function_get_shadow_stats_exists(self):
        """Verify function get_shadow_stats is exported."""
        mod = importlib.import_module("runtime.shadow_mode")
        assert hasattr(mod, "get_shadow_stats")
        assert callable(mod.get_shadow_stats)

    def test_function_reset_shadow_stats_exists(self):
        """Verify function reset_shadow_stats is exported."""
        mod = importlib.import_module("runtime.shadow_mode")
        assert hasattr(mod, "reset_shadow_stats")
        assert callable(mod.reset_shadow_stats)
