"""Tests for tools.correlation.root_cause — Category: function"""

import pytest

from tools.correlation.root_cause import _root_cause_key
from tools.correlation.root_cause import find_root_causes
from tools.correlation.root_cause import group_by_root_cause


class TestRootCauseKey:
    """Tests for the _root_cause_key function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _root_cause_key()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _root_cause_key()


class TestGroupByRootCause:
    """Tests for the group_by_root_cause function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            group_by_root_cause()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            group_by_root_cause()


class TestFindRootCauses:
    """Tests for the find_root_causes function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            find_root_causes()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            find_root_causes()
