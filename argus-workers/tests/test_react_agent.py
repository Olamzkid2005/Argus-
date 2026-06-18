"""Smoke tests for agent/react_agent.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.react_agent."""

    def test_module_imports(self):
        """Verify react_agent.py imports cleanly."""
        mod = importlib.import_module("agent.react_agent")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ReActAgent is available."""
        mod = importlib.import_module("agent.react_agent")
        assert hasattr(mod, "ReActAgent")
        assert callable(mod.ReActAgent)
