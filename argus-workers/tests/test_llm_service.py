"""Smoke tests for llm_service.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for llm_service."""

    def test_module_imports(self):
        """Verify llm_service.py imports cleanly."""
        mod = importlib.import_module("llm_service")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class CostTracker is available."""
        mod = importlib.import_module("llm_service")
        assert hasattr(mod, "CostTracker")
        assert callable(mod.CostTracker)
