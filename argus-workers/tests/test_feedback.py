"""Smoke tests for models/feedback.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for models.feedback."""

    def test_module_imports(self):
        """Verify feedback.py imports cleanly."""
        mod = importlib.import_module("models.feedback")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class FindingFeedback is available."""
        mod = importlib.import_module("models.feedback")
        assert hasattr(mod, "FindingFeedback")
        assert callable(mod.FindingFeedback)
