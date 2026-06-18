"""Tests for agent.agent_action — Category: class"""

import pytest

from agent.agent_action import AgentAction


class TestAgentAction:
    """Tests for the AgentAction class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            AgentAction()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            AgentAction()
