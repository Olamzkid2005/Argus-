"""Smoke tests for tools/mcp_bridge.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.mcp_bridge."""

    def test_module_imports(self):
        """Verify mcp_bridge.py imports cleanly."""
        mod = importlib.import_module("tools.mcp_bridge")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class MCPToolBridge is available."""
        mod = importlib.import_module("tools.mcp_bridge")
        assert hasattr(mod, "MCPToolBridge")
        assert callable(mod.MCPToolBridge)
