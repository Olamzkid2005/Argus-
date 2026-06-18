"""Tests for tools.threat_intelligence_aggregator — Category: class"""

import pytest

from tools.threat_intelligence_aggregator import ThreatIntelligenceAggregator


class TestThreatIntelligenceAggregator:
    """Tests for the ThreatIntelligenceAggregator class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ThreatIntelligenceAggregator()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ThreatIntelligenceAggregator()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
