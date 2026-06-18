"""Smoke tests for tools/correlation/attack_chain_detector.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.correlation.attack_chain_detector."""

    def test_module_imports(self):
        """Verify attack_chain_detector.py imports cleanly."""
        mod = importlib.import_module("tools.correlation.attack_chain_detector")
        assert mod is not None

    def test_function_detect_attack_chains_exists(self):
        """Verify function detect_attack_chains is exported."""
        mod = importlib.import_module("tools.correlation.attack_chain_detector")
        assert hasattr(mod, "detect_attack_chains")
        assert callable(mod.detect_attack_chains)
