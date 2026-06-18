"""Tests for agent.agent_runtime — Category: class"""

import pytest

from agent.agent_runtime import AgentRuntime


class TestAgentRuntime:
    """Tests for the AgentRuntime class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            AgentRuntime()

    def test_str_repr(self):
        """String representation not available."""
        with pytest.raises(TypeError):
            AgentRuntime()
