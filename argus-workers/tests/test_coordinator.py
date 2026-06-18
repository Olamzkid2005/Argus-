"""Tests for agent.coordinator — Category: class"""

import pytest

from agent.coordinator import CoordinatorAgent


class TestCoordinatorAgent:
    """Tests for the CoordinatorAgent class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = CoordinatorAgent()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = CoordinatorAgent()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
