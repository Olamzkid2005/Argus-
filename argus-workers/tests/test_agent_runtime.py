"""Smoke tests for agent/agent_runtime.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.agent_runtime."""

    def test_module_imports(self):
        """Verify agent_runtime.py imports cleanly."""
        mod = importlib.import_module("agent.agent_runtime")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AgentRuntime is available."""
        mod = importlib.import_module("agent.agent_runtime")
        assert hasattr(mod, "AgentRuntime")
        assert callable(mod.AgentRuntime)
