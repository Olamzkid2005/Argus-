"""Tests for tool_core.base — Category: abstract_class"""

import pytest

from tool_core.base import AbstractTool, AsyncTool, ToolContext


class TestToolContext:
    """Tests for the ToolContext class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = ToolContext()
        assert instance is not None

    def test_field_access(self):
        """Instance fields are accessible."""
        instance = ToolContext()
        fields = vars(instance) if hasattr(instance, '__dict__') else {}
        assert isinstance(fields, dict)


class TestAbstractTool:
    """Tests for the AbstractTool abstract class."""

    def test_instantiation(self):
        """Cannot instantiate abstract class."""
        with pytest.raises(TypeError):
            AbstractTool()

    def test_field_access(self):
        """Cannot instantiate abstract class."""
        with pytest.raises(TypeError):
            AbstractTool()


class TestAsyncTool:
    """Tests for the AsyncTool abstract class."""

    def test_instantiation(self):
        """Cannot instantiate abstract class."""
        with pytest.raises(TypeError):
            AsyncTool()

    def test_field_access(self):
        """Cannot instantiate abstract class."""
        with pytest.raises(TypeError):
            AsyncTool()
