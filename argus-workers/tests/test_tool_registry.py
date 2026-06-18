"""Smoke tests for agent/tool_registry.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.tool_registry."""

    def test_module_imports(self):
        """Verify tool_registry.py imports cleanly."""
        mod = importlib.import_module("agent.tool_registry")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ToolRegistry is available."""
        mod = importlib.import_module("agent.tool_registry")
        assert hasattr(mod, "ToolRegistry")
        assert callable(mod.ToolRegistry)
