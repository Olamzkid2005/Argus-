"""Tests for agent.tool_registry — Category: class"""

import pytest

from agent.tool_registry import ToolRegistry


class TestToolRegistry:
    """Tests for the ToolRegistry class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ToolRegistry()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = ToolRegistry()
        assert instance is not None
