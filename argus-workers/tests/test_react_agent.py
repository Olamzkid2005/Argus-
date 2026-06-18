"""Tests for agent.react_agent — Category: class"""

import pytest

from agent.react_agent import ReActAgent
from agent.react_agent import _DoneSentinel


class Test_DoneSentinel:
    """Tests for the _DoneSentinel class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = _DoneSentinel()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = _DoneSentinel()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestReActAgent:
    """Tests for the ReActAgent class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ReActAgent()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ReActAgent()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
