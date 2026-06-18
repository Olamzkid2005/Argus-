"""Smoke tests for models/confidence_scorer.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for models.confidence_scorer."""

    def test_module_imports(self):
        """Verify confidence_scorer.py imports cleanly."""
        mod = importlib.import_module("models.confidence_scorer")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ConfidenceScorer is available."""
        mod = importlib.import_module("models.confidence_scorer")
        assert hasattr(mod, "ConfidenceScorer")
        assert callable(mod.ConfidenceScorer)
