"""Tests for agent.agent_result — Category: class"""

import pytest

from agent.agent_result import AgentResult


class TestAgentResult:
    """Tests for the AgentResult class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            AgentResult()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            AgentResult()
            str(AgentResult())
