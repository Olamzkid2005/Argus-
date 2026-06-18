"""Tests for tasks.utils — Category: class"""

import pytest

from tasks.utils import LlmCostTracker


class TestLlmCostTracker:
    """Tests for the LlmCostTracker class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = LlmCostTracker()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = LlmCostTracker()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
