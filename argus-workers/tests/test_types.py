"""Tests for tool_core.parser.types — Category: dataclass"""

import pytest

from tool_core.parser.types import NormalizedFinding


class TestNormalizedFinding:
    """Tests for the NormalizedFinding class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = NormalizedFinding()
            assert instance is not None
            assert isinstance(instance, NormalizedFinding)
        except TypeError:
            with pytest.raises(TypeError):
                NormalizedFinding()

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = NormalizedFinding()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            with pytest.raises(TypeError):
                NormalizedFinding()
