"""Smoke tests for tools/verification/evidence_collector.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.verification.evidence_collector."""

    def test_module_imports(self):
        """Verify evidence_collector.py imports cleanly."""
        mod = importlib.import_module("tools.verification.evidence_collector")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class VerificationEvidenceCollector is available."""
        mod = importlib.import_module("tools.verification.evidence_collector")
        assert hasattr(mod, "VerificationEvidenceCollector")
        assert callable(mod.VerificationEvidenceCollector)
