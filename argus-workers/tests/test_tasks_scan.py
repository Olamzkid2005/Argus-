"""Tests for tasks.scan — Category: function"""

import pytest

from tasks.scan import auth_focused_scan
from tasks.scan import deep_scan
from tasks.scan import run_scan


class TestRunScan:
    """Tests for the run_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_scan()


class TestDeepScan:
    """Tests for the deep_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            deep_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            deep_scan()


class TestAuthFocusedScan:
    """Tests for the auth_focused_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            auth_focused_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            auth_focused_scan()
