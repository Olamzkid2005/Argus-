"""Smoke tests for agent_loop.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent_loop."""

    def test_module_imports(self):
        """Verify agent_loop.py imports cleanly."""
        mod = importlib.import_module("agent_loop")
        assert mod is not None
