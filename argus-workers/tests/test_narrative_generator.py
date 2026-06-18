"""Smoke tests for tools/attack_paths/narrative_generator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_paths.narrative_generator."""

    def test_module_imports(self):
        """Verify narrative_generator.py imports cleanly."""
        mod = importlib.import_module("tools.attack_paths.narrative_generator")
        assert mod is not None

    def test_function_generate_narrative_exists(self):
        """Verify function generate_narrative is exported."""
        mod = importlib.import_module("tools.attack_paths.narrative_generator")
        assert hasattr(mod, "generate_narrative")
        assert callable(mod.generate_narrative)
