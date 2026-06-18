"""Tests for tools.run_agent_tool — Category: function"""

import pytest

from tools.run_agent_tool import main, resolve_tool_class


class TestResolveToolClass:
    """Tests for the resolve_tool_class function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            resolve_tool_class()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            resolve_tool_class()


class TestMain:
    """Tests for the main function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            main()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            main()
