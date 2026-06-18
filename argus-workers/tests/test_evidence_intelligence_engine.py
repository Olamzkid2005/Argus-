"""Smoke tests for tools/evidence_intelligence_engine.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.evidence_intelligence_engine."""

    def test_module_imports(self):
        """Verify evidence_intelligence_engine.py imports cleanly."""
        mod = importlib.import_module("tools.evidence_intelligence_engine")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class EvidenceIntelligenceEngine is available."""
        mod = importlib.import_module("tools.evidence_intelligence_engine")
        assert hasattr(mod, "EvidenceIntelligenceEngine")
        assert callable(mod.EvidenceIntelligenceEngine)
