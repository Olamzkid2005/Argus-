"""Smoke tests for tool_core/parser/types.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tool_core.parser.types."""

    def test_module_imports(self):
        """Verify types.py imports cleanly."""
        mod = importlib.import_module("tool_core.parser.types")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class NormalizedFinding is available."""
        mod = importlib.import_module("tool_core.parser.types")
        assert hasattr(mod, "NormalizedFinding")
        assert callable(mod.NormalizedFinding)
