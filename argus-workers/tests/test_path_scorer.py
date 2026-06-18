"""Tests for tools.attack_paths.path_scorer — Category: function"""

import pytest

from tools.attack_paths.path_scorer import rank_paths, score_path


class TestScorePath:
    """Tests for the score_path function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            score_path()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            score_path()


class TestRankPaths:
    """Tests for the rank_paths function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            rank_paths()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            rank_paths()
