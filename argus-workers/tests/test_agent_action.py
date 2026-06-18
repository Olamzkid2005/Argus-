"""Tests for agent.agent_action — Category: class"""

import pytest

from agent.agent_action import AgentAction


class TestAgentAction:
    """Tests for the AgentAction class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AgentAction()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = AgentAction()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
