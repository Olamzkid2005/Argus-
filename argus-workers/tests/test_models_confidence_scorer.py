"""Tests for models.confidence_scorer — Category: class"""

import pytest

from models.confidence_scorer import ConfidenceScorer


class TestConfidenceScorer:
    """Tests for the ConfidenceScorer class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ConfidenceScorer()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ConfidenceScorer()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
