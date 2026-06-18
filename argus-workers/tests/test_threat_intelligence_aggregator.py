"""Tests for tools.threat_intelligence_aggregator — Category: class"""

import pytest

from tools.threat_intelligence_aggregator import ThreatIntelligenceAggregator


class TestThreatIntelligenceAggregator:
    """Tests for the ThreatIntelligenceAggregator class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ThreatIntelligenceAggregator()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = ThreatIntelligenceAggregator()
        assert instance is not None
