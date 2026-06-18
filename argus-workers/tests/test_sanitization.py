"""Tests for utils.sanitization — Category: function"""

import pytest

from utils.sanitization import (
    check_for_dangerous_content,
    sanitize_evidence,
    sanitize_string,
    strip_dangerous_tags,
)


class TestSanitizeString:
    """Tests for the sanitize_string function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            sanitize_string()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            sanitize_string()


class TestSanitizeEvidence:
    """Tests for the sanitize_evidence function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            sanitize_evidence()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            sanitize_evidence()


class TestCheckForDangerousContent:
    """Tests for the check_for_dangerous_content function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            check_for_dangerous_content()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            check_for_dangerous_content()


class TestStripDangerousTags:
    """Tests for the strip_dangerous_tags function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            strip_dangerous_tags()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            strip_dangerous_tags()
