"""Smoke tests for parsers/parsers/trivy.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.trivy."""

    def test_module_imports(self):
        """Verify trivy.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.trivy")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class TrivyParser is available."""
        mod = importlib.import_module("parsers.parsers.trivy")
        assert hasattr(mod, "TrivyParser")
        assert callable(mod.TrivyParser)
