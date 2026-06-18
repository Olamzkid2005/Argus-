"""Tests for tool_core.finding_builder — Category: class"""

import pytest

from tool_core.finding_builder import FindingBuilder


class TestFindingBuilder:
    """Tests for the FindingBuilder class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            FindingBuilder()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            FindingBuilder()
            str(FindingBuilder())
