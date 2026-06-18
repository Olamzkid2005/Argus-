"""Tests for models.confidence_scorer — Category: class"""

import pytest

from models.confidence_scorer import ConfidenceScorer


class TestConfidenceScorer:
    """Tests for the ConfidenceScorer class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ConfidenceScorer()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ConfidenceScorer()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
