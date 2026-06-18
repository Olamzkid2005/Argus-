"""Smoke tests for tools/verification/confidence_scorer.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.verification.confidence_scorer."""

    def test_module_imports(self):
        """Verify confidence_scorer.py imports cleanly."""
        mod = importlib.import_module("tools.verification.confidence_scorer")
        assert mod is not None

    def test_function_score_confidence_exists(self):
        """Verify function score_confidence is exported."""
        mod = importlib.import_module("tools.verification.confidence_scorer")
        assert hasattr(mod, "score_confidence")
        assert callable(mod.score_confidence)
