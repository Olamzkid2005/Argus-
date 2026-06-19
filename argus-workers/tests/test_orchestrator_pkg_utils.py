"""Tests for orchestrator_pkg.utils — Category: function"""

import pytest

from orchestrator_pkg.utils import (
    get_nuclei_templates_path,
    get_wordlist_path,
    tool_timeout,
)


class TestGetWordlistPath:
    """Tests for the get_wordlist_path function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_wordlist_path()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_wordlist_path()


class TestGetNucleiTemplatesPath:
    """Tests for the get_nuclei_templates_path function."""

    def test_basic_execution(self):
        """Function executes successfully."""
        instance = get_nuclei_templates_path()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns a PosixPath."""
        from pathlib import PosixPath
        instance = get_nuclei_templates_path()
        assert isinstance(instance, PosixPath)


class TestToolTimeout:
    """Tests for the tool_timeout function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            tool_timeout()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            tool_timeout()
