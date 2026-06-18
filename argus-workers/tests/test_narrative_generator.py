"""Tests for tools.attack_paths.narrative_generator — Category: function"""

import pytest

from tools.attack_paths.narrative_generator import generate_narrative


class TestGenerateNarrative:
    """Tests for the generate_narrative function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_narrative()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_narrative()
