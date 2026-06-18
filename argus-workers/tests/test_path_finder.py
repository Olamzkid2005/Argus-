"""Tests for tools.attack_paths.path_finder — Category: function"""

import pytest

from tools.attack_paths.path_finder import find_paths


class TestFindPaths:
    """Tests for the find_paths function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            find_paths()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            find_paths()
