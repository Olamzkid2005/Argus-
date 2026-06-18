"""Smoke tests for tools/verification_agent.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.verification_agent."""

    def test_module_imports(self):
        """Verify verification_agent.py imports cleanly."""
        mod = importlib.import_module("tools.verification_agent")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class VerificationAgent is available."""
        mod = importlib.import_module("tools.verification_agent")
        assert hasattr(mod, "VerificationAgent")
        assert callable(mod.VerificationAgent)
