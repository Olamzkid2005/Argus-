"""Smoke tests for tools/tool_utils.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.tool_utils."""

    def test_module_imports(self):
        """Verify tool_utils.py imports cleanly."""
        mod = importlib.import_module("tools.tool_utils")
        assert mod is not None

    def test_function_get_augmented_path_exists(self):
        """Verify function get_augmented_path is exported."""
        mod = importlib.import_module("tools.tool_utils")
        assert hasattr(mod, "get_augmented_path")
        assert callable(mod.get_augmented_path)

    def test_function_resolve_tool_binary_exists(self):
        """Verify function resolve_tool_binary is exported."""
        mod = importlib.import_module("tools.tool_utils")
        assert hasattr(mod, "resolve_tool_binary")
        assert callable(mod.resolve_tool_binary)

    def test_function_is_tool_available_exists(self):
        """Verify function is_tool_available is exported."""
        mod = importlib.import_module("tools.tool_utils")
        assert hasattr(mod, "is_tool_available")
        assert callable(mod.is_tool_available)
