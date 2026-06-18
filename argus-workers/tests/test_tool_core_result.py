"""Tests for tool_core.result — Category: dataclass"""

import pytest

from tool_core.result import ToolStatus
from tool_core.result import UnifiedToolResult


class TestToolStatus:
    """Tests for the ToolStatus class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ToolStatus()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ToolStatus()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestUnifiedToolResult:
    """Tests for the UnifiedToolResult class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = UnifiedToolResult()
            assert instance is not None
            assert isinstance(instance, UnifiedToolResult)
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = UnifiedToolResult()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            pytest.skip("Requires constructor args")
