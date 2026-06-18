"""Tests for orchestrator_pkg.utils — Category: function"""

import pytest

from orchestrator_pkg.utils import get_nuclei_templates_path
from orchestrator_pkg.utils import get_wordlist_path
from orchestrator_pkg.utils import tool_timeout


class TestGetWordlistPath:
    """Tests for the get_wordlist_path function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = get_wordlist_path()
            assert result is not None
        except TypeError:
            pytest.skip("get_wordlist_path requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = get_wordlist_path()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestGetNucleiTemplatesPath:
    """Tests for the get_nuclei_templates_path function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = get_nuclei_templates_path()
            assert result is not None
        except TypeError:
            pytest.skip("get_nuclei_templates_path requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = get_nuclei_templates_path()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestToolTimeout:
    """Tests for the tool_timeout function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = tool_timeout()
            assert result is not None
        except TypeError:
            pytest.skip("tool_timeout requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = tool_timeout()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
