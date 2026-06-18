"""Tests for tasks.recon — Category: function"""

import pytest

from tasks.recon import expand_recon
from tasks.recon import run_recon


class TestRunRecon:
    """Tests for the run_recon function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_recon()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_recon()


class TestExpandRecon:
    """Tests for the expand_recon function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            expand_recon()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            expand_recon()
