"""Smoke tests for agent/tools/login_tool.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.tools.login_tool."""

    def test_module_imports(self):
        """Verify login_tool.py imports cleanly."""
        mod = importlib.import_module("agent.tools.login_tool")
        assert mod is not None

    def test_function_run_login_exists(self):
        """Verify function run_login is exported."""
        mod = importlib.import_module("agent.tools.login_tool")
        assert hasattr(mod, "run_login")
        assert callable(mod.run_login)
