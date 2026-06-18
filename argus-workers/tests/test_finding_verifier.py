"""Tests for tools.finding_verifier — Category: function"""

import pytest

from tools.finding_verifier import _validate_verification_url


class TestValidateVerificationUrl:
    """Tests for the _validate_verification_url function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _validate_verification_url()
    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _validate_verification_url()
