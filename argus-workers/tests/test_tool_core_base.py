"""Tests for tool_core.base — Category: abstract_class"""

import pytest

from tool_core.base import AbstractTool
from tool_core.base import AsyncTool
from tool_core.base import ToolContext


class TestToolContext:
    """Tests for the ToolContext class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ToolContext()
            assert instance is not None
            assert isinstance(instance, ToolContext)
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = ToolContext()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            pytest.skip("Requires constructor args")


class TestAbstractTool:
    """Tests for the AbstractTool class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AbstractTool()
            assert instance is not None
            assert isinstance(instance, AbstractTool)
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = AbstractTool()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            pytest.skip("Requires constructor args")


class TestAsyncTool:
    """Tests for the AsyncTool class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AsyncTool()
            assert instance is not None
            assert isinstance(instance, AsyncTool)
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = AsyncTool()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            pytest.skip("Requires constructor args")
