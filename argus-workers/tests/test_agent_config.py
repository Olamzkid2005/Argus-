"""Smoke tests for agent/agent_config.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.agent_config."""

    def test_module_imports(self):
        """Verify agent_config.py imports cleanly."""
        mod = importlib.import_module("agent.agent_config")
        assert mod is not None
