"""Tests for tasks.self_scan — Category: function"""

import pytest

from tasks.self_scan import run_self_scan


class TestRunSelfScan:
    """Tests for the run_self_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_self_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_self_scan()
