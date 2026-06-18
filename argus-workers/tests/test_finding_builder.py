"""Smoke tests for tool_core/finding_builder.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tool_core.finding_builder."""

    def test_module_imports(self):
        """Verify finding_builder.py imports cleanly."""
        mod = importlib.import_module("tool_core.finding_builder")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class FindingBuilder is available."""
        mod = importlib.import_module("tool_core.finding_builder")
        assert hasattr(mod, "FindingBuilder")
        assert callable(mod.FindingBuilder)
