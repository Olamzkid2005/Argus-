"""Smoke tests for orchestrator_pkg/normalizer_utils.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for orchestrator_pkg.normalizer_utils."""

    def test_module_imports(self):
        """Verify normalizer_utils.py imports cleanly."""
        mod = importlib.import_module("orchestrator_pkg.normalizer_utils")
        assert mod is not None

    def test_function_normalize_finding_exists(self):
        """Verify function normalize_finding is exported."""
        mod = importlib.import_module("orchestrator_pkg.normalizer_utils")
        assert hasattr(mod, "normalize_finding")
        assert callable(mod.normalize_finding)
