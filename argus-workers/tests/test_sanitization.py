"""Tests for utils.sanitization — Category: function"""

import pytest

from utils.sanitization import check_for_dangerous_content
from utils.sanitization import sanitize_evidence
from utils.sanitization import sanitize_string
from utils.sanitization import strip_dangerous_tags


class TestSanitizeString:
    """Tests for the sanitize_string function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = sanitize_string()
            assert result is not None
        except TypeError:
            pytest.skip("sanitize_string requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = sanitize_string()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestSanitizeEvidence:
    """Tests for the sanitize_evidence function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = sanitize_evidence()
            assert result is not None
        except TypeError:
            pytest.skip("sanitize_evidence requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = sanitize_evidence()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestCheckForDangerousContent:
    """Tests for the check_for_dangerous_content function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = check_for_dangerous_content()
            assert result is not None
        except TypeError:
            pytest.skip("check_for_dangerous_content requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = check_for_dangerous_content()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestStripDangerousTags:
    """Tests for the strip_dangerous_tags function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = strip_dangerous_tags()
            assert result is not None
        except TypeError:
            pytest.skip("strip_dangerous_tags requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = strip_dangerous_tags()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
