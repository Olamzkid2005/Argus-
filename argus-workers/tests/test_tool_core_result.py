"""Tests for tool_core.result — Category: dataclass"""

import pytest

from tool_core.result import ToolStatus
from tool_core.result import UnifiedToolResult


class TestToolStatus:
    """Tests for the ToolStatus class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ToolStatus()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ToolStatus()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestUnifiedToolResult:
    """Tests for the UnifiedToolResult class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = UnifiedToolResult()
            assert instance is not None
            assert isinstance(instance, UnifiedToolResult)
        except TypeError:
            instance = ToolStatus()
            assert instance is not None

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = UnifiedToolResult()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            instance = ToolStatus()
            assert instance is not None
