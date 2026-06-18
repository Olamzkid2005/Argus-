"""Smoke tests for tools/run_agent_tool.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.run_agent_tool."""

    def test_module_imports(self):
        """Verify run_agent_tool.py imports cleanly."""
        mod = importlib.import_module("tools.run_agent_tool")
        assert mod is not None

    def test_function_resolve_tool_class_exists(self):
        """Verify function resolve_tool_class is exported."""
        mod = importlib.import_module("tools.run_agent_tool")
        assert hasattr(mod, "resolve_tool_class")
        assert callable(mod.resolve_tool_class)

    def test_function_main_exists(self):
        """Verify function main is exported."""
        mod = importlib.import_module("tools.run_agent_tool")
        assert hasattr(mod, "main")
        assert callable(mod.main)
