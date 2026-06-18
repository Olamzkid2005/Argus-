"""Smoke tests for agent/tools/register_tool.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.tools.register_tool."""

    def test_module_imports(self):
        """Verify register_tool.py imports cleanly."""
        mod = importlib.import_module("agent.tools.register_tool")
        assert mod is not None

    def test_function_generate_credentials_exists(self):
        """Verify function generate_credentials is exported."""
        mod = importlib.import_module("agent.tools.register_tool")
        assert hasattr(mod, "generate_credentials")
        assert callable(mod.generate_credentials)

    def test_function_run_register_exists(self):
        """Verify function run_register is exported."""
        mod = importlib.import_module("agent.tools.register_tool")
        assert hasattr(mod, "run_register")
        assert callable(mod.run_register)
