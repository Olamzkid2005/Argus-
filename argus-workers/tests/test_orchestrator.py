"""Smoke tests for orchestrator_pkg/orchestrator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for orchestrator_pkg.orchestrator."""

    def test_module_imports(self):
        """Verify orchestrator.py imports cleanly."""
        mod = importlib.import_module("orchestrator_pkg.orchestrator")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class EngagementTimeoutError is available."""
        mod = importlib.import_module("orchestrator_pkg.orchestrator")
        assert hasattr(mod, "EngagementTimeoutError")
        assert callable(mod.EngagementTimeoutError)
