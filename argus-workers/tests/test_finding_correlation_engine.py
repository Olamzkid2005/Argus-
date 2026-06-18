"""Smoke tests for tools/finding_correlation_engine.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.finding_correlation_engine."""

    def test_module_imports(self):
        """Verify finding_correlation_engine.py imports cleanly."""
        mod = importlib.import_module("tools.finding_correlation_engine")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class FindingCorrelationEngine is available."""
        mod = importlib.import_module("tools.finding_correlation_engine")
        assert hasattr(mod, "FindingCorrelationEngine")
        assert callable(mod.FindingCorrelationEngine)
