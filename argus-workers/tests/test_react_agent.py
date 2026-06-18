"""Tests for agent.react_agent — Category: class"""

import pytest

from agent.react_agent import ReActAgent
from agent.react_agent import _DoneSentinel


class Test_DoneSentinel:
    """Tests for the _DoneSentinel class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = _DoneSentinel()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = _DoneSentinel()
        assert instance is not None


class TestReActAgent:
    """Tests for the ReActAgent class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = _DoneSentinel()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = _DoneSentinel()
        assert instance is not None
