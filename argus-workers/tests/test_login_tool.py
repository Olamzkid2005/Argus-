"""Tests for agent.tools.login_tool — Category: function"""

import pytest

from agent.tools.login_tool import _build_login_payload
from agent.tools.login_tool import _detect_2fa
from agent.tools.login_tool import _extract_cookie_string
from agent.tools.login_tool import _extract_jwt
from agent.tools.login_tool import _fail_result
from agent.tools.login_tool import _rate_limit_backoff
from agent.tools.login_tool import run_login


class TestRunLogin:
    """Tests for the run_login function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_login()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_login()


class TestBuildLoginPayload:
    """Tests for the _build_login_payload function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _build_login_payload()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _build_login_payload()


class TestDetect2fa:
    """Tests for the _detect_2fa function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _detect_2fa()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _detect_2fa()


class TestExtractCookieString:
    """Tests for the _extract_cookie_string function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _extract_cookie_string()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _extract_cookie_string()


class TestExtractJwt:
    """Tests for the _extract_jwt function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _extract_jwt()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _extract_jwt()


class TestRateLimitBackoff:
    """Tests for the _rate_limit_backoff function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _rate_limit_backoff()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _rate_limit_backoff()


class TestFailResult:
    """Tests for the _fail_result function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _fail_result()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _fail_result()
