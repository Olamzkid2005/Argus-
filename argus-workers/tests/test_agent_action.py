"""Smoke tests for agent/agent_action.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.agent_action."""

    def test_module_imports(self):
        """Verify agent_action.py imports cleanly."""
        mod = importlib.import_module("agent.agent_action")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AgentAction is available."""
        mod = importlib.import_module("agent.agent_action")
        assert hasattr(mod, "AgentAction")
        assert callable(mod.AgentAction)
