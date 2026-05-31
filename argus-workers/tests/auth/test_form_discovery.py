"""Tests for form discovery utility."""

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "form_discovery", "agent/form_discovery.py",
)
_fd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fd)


class TestExtractFormFields:
    """HTML form field extraction."""

    def test_standard_login_form(self):
        html = """
        <html><body>
        <form method="post" action="/login">
          <input name="email" type="email">
          <input name="password" type="password">
          <button type="submit">Sign In</button>
        </form>
        </body></html>
        """
        fields = _fd._extract_form_fields(html, "login")
        assert fields.get("email") == "email"
        assert fields.get("password") == "password"
        assert fields.get("form_action") == "/login"
        assert fields.get("form_method") == "POST"

    def test_registration_form_with_csrf(self):
        html = """
        <html><body>
        <form method="post" action="/register">
          <input name="_token" type="hidden" value="abc123">
          <input name="email" type="email">
          <input name="password" type="password">
          <input name="password_confirmation" type="password">
          <button type="submit">Register</button>
        </form>
        </body></html>
        """
        fields = _fd._extract_form_fields(html, "register")
        assert fields.get("email") == "email"
        assert fields.get("password") == "password"
        assert fields.get("confirm") == "password_confirmation"
        assert fields.get("csrf") == "_token"
        assert fields.get("csrf_value") == "abc123"

    def test_no_form_tag(self):
        html = "<html><body><p>No form here</p></body></html>"
        fields = _fd._extract_form_fields(html)
        assert fields == {}

    def test_form_without_password(self):
        """A form without a password field should still extract email."""
        html = """
        <form method="post">
          <input name="email" type="email">
          <input name="name" type="text">
        </form>
        """
        fields = _fd._extract_form_fields(html)
        assert fields.get("email") == "email"
        assert "password" not in fields

    def test_csrf_token_value_extraction(self):
        html = """
        <form method="post">
          <input name="csrf_token" type="hidden" value="token123">
          <input name="email" type="email">
          <input name="password" type="password">
        </form>
        """
        fields = _fd._extract_form_fields(html)
        assert fields.get("csrf") == "csrf_token"
        assert fields.get("csrf_value") == "token123"


class TestVerificationDetection:
    """Email verification requirement detection."""

    class _MockResponse:
        def __init__(self, text):
            self.text = text

    def test_verify_email_detected(self):
        resp = self._MockResponse("Please verify your email address to continue")
        assert _fd.has_verification_requirement(resp) is True

    def test_activation_link_detected(self):
        resp = self._MockResponse("Check your email for the activation link")
        assert _fd.has_verification_requirement(resp) is True

    def test_no_verification(self):
        resp = self._MockResponse("Welcome to your dashboard")
        assert _fd.has_verification_requirement(resp) is False

    def test_empty_response(self):
        resp = self._MockResponse("")
        assert _fd.has_verification_requirement(resp) is False


class TestErrorCodes:
    """Error code completeness."""

    def test_required_codes_present(self):
        required = [
            "FORM_NOT_FOUND", "CAPTCHA_DETECTED",
            "EMAIL_VERIFICATION_REQUIRED", "INVALID_CREDENTIALS",
            "2FA_REQUIRED", "RATE_LIMITED", "ACCOUNT_LOCKED",
        ]
        for code in required:
            assert code in _fd.ERROR_CODES, f"Missing error code: {code}"

    def test_all_codes_have_messages(self):
        for code, message in _fd.ERROR_CODES.items():
            assert message, f"Error code {code} has no message"
