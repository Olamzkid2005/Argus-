"""Smoke tests for models/candidate_list.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for models.candidate_list."""

    def test_module_imports(self):
        """Verify candidate_list.py imports cleanly."""
        mod = importlib.import_module("models.candidate_list")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class CandidateSource is available."""
        mod = importlib.import_module("models.candidate_list")
        assert hasattr(mod, "CandidateSource")
        assert callable(mod.CandidateSource)
