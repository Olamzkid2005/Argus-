"""Smoke tests for tools/threat_intelligence_aggregator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.threat_intelligence_aggregator."""

    def test_module_imports(self):
        """Verify threat_intelligence_aggregator.py imports cleanly."""
        mod = importlib.import_module("tools.threat_intelligence_aggregator")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ThreatIntelligenceAggregator is available."""
        mod = importlib.import_module("tools.threat_intelligence_aggregator")
        assert hasattr(mod, "ThreatIntelligenceAggregator")
        assert callable(mod.ThreatIntelligenceAggregator)
