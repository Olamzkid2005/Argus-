"""Tests for agent.coordinator — Category: class"""

import pytest

from agent.coordinator import CoordinatorAgent


class TestCoordinatorAgent:
    """Tests for the CoordinatorAgent class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            CoordinatorAgent()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            CoordinatorAgent()
