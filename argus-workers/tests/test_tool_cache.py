"""Smoke tests for tools/tool_cache.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.tool_cache."""

    def test_module_imports(self):
        """Verify tool_cache.py imports cleanly."""
        mod = importlib.import_module("tools.tool_cache")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ToolCache is available."""
        mod = importlib.import_module("tools.tool_cache")
        assert hasattr(mod, "ToolCache")
        assert callable(mod.ToolCache)

    def test_function_get_cached_tool_exists(self):
        """Verify function get_cached_tool is exported."""
        mod = importlib.import_module("tools.tool_cache")
        assert hasattr(mod, "get_cached_tool")
        assert callable(mod.get_cached_tool)
