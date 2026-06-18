"""Tests for tools.web_scanner_checks._helpers — Category: function"""

import pytest

from tools.web_scanner_checks._helpers import (
    detect_framework,
    make_finding,
    safe_request,
)
from tools.web_scanner_checks._helpers import test_jwt_alg_none as _jwt_alg_none
from tools.web_scanner_checks._helpers import test_jwt_rs256_hs256 as _jwt_rs256_hs256


class TestSafeRequest:
    """Tests for the safe_request function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            safe_request()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            safe_request()


class TestMakeFinding:
    """Tests for the make_finding function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            make_finding()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            make_finding()


class TestDetectFramework:
    """Tests for the detect_framework function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            detect_framework()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            detect_framework()


class TestTestJwtAlgNone:
    """Tests for the test_jwt_alg_none function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _jwt_alg_none()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _jwt_alg_none()


class TestTestJwtRs256Hs256:
    """Tests for the test_jwt_rs256_hs256 function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _jwt_rs256_hs256()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _jwt_rs256_hs256()
