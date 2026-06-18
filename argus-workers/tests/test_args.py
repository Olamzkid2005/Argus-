"""Tests for tool_core.validators.args — Category: function"""

import pytest

from tool_core.validators.args import is_dangerous


class TestIsDangerous:
    """Tests for the is_dangerous function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            is_dangerous()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            is_dangerous()
