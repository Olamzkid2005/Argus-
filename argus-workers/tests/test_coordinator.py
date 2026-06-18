"""Smoke tests for agent/coordinator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.coordinator."""

    def test_module_imports(self):
        """Verify coordinator.py imports cleanly."""
        mod = importlib.import_module("agent.coordinator")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class CoordinatorAgent is available."""
        mod = importlib.import_module("agent.coordinator")
        assert hasattr(mod, "CoordinatorAgent")
        assert callable(mod.CoordinatorAgent)

    def test_function_create_phase_agent_exists(self):
        """Verify function create_phase_agent is exported."""
        mod = importlib.import_module("agent.coordinator")
        assert hasattr(mod, "create_phase_agent")
        assert callable(mod.create_phase_agent)
