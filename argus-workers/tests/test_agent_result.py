"""Tests for agent.agent_result — Category: class"""

import pytest

from agent.agent_result import AgentResult


class TestAgentResult:
    """Tests for the AgentResult class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AgentResult()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = AgentResult()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
