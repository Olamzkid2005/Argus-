"""Tests for tools.threat_intelligence_aggregator — Category: class"""


from tools.threat_intelligence_aggregator import ThreatIntelligenceAggregator


class TestThreatIntelligenceAggregator:
    """Tests for the ThreatIntelligenceAggregator class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = ThreatIntelligenceAggregator()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ThreatIntelligenceAggregator()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
