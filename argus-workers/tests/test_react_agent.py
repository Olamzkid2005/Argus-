"""Tests for agent.react_agent — Category: class"""

import pytest

from agent.react_agent import ReActAgent


class TestReActAgent:
    """Tests for the ReActAgent class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            ReActAgent()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            ReActAgent()
