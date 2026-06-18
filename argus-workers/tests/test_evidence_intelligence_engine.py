"""Tests for tools.evidence_intelligence_engine — Category: class"""

import pytest

from tools.evidence_intelligence_engine import EvidenceIntelligenceEngine


class TestEvidenceIntelligenceEngine:
    """Tests for the EvidenceIntelligenceEngine class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = EvidenceIntelligenceEngine()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = EvidenceIntelligenceEngine()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
