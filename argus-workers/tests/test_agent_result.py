"""Smoke tests for agent/agent_result.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.agent_result."""

    def test_module_imports(self):
        """Verify agent_result.py imports cleanly."""
        mod = importlib.import_module("agent.agent_result")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AgentResult is available."""
        mod = importlib.import_module("agent.agent_result")
        assert hasattr(mod, "AgentResult")
        assert callable(mod.AgentResult)
