"""Tests for ``_build_login_payload`` field permutation logic.

Covers:
- Form mode: uses extracted field names, toggles JSON on odd attempts, includes CSRF
- API mode: flat list of (permutation, content_type) pairs
- ``_is_json`` is a Python boolean, not a string
- Returns None when all combinations exhausted
"""

from __future__ import annotations

import importlib.util
import os

# ── Import login_tool without triggering agent/__init__.py ──

_spec = importlib.util.spec_from_file_location(
    "login_tool",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "agent",
        "tools",
        "login_tool.py",
    ),
)
_lt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lt)


# ── Tests for _build_login_payload ──


class TestBuildLoginPayloadFormMode:
    """Form mode — uses extracted HTML field names."""

    def test_form_mode_uses_extracted_field_names(self) -> None:
        """Form mode builds payload from discovered form fields."""
        fields = {"email": "user_email", "password": "passwd"}
        payload = _lt._build_login_payload(
            "admin@test.com", "secret123", fields, "form", 0
        )
        assert payload is not None
        assert payload.get("user_email") == "admin@test.com"
        assert payload.get("passwd") == "secret123"

    def test_form_mode_returns_pure_fields_in_body_data(self) -> None:
        """The body data (after filtering ``_`` keys) contains only credential fields."""
        fields = {"email": "email", "password": "password"}
        payload = _lt._build_login_payload("a@b.com", "s3cret", fields, "form", 0)
        assert payload is not None
        body_data = {k: v for k, v in payload.items() if not k.startswith("_")}
        assert body_data == {"email": "a@b.com", "password": "s3cret"}

    def test_form_mode_always_form_encoded(self) -> None:
        """Form mode always uses form-encoded (``_is_json`` is always False)."""
        fields = {"email": "email", "password": "password"}
        even = _lt._build_login_payload("a@b.com", "s3cret", fields, "form", 0)
        odd = _lt._build_login_payload("a@b.com", "s3cret", fields, "form", 1)
        assert even is not None and odd is not None
        assert even.get("_is_json") is False
        assert odd.get("_is_json") is False  # form mode never uses JSON

    def test_form_mode_includes_csrf_when_present(self) -> None:
        """Form mode includes the CSRF token value if available."""
        fields = {
            "email": "email",
            "password": "password",
            "csrf": "csrf_token",
            "csrf_value": "tok123",
        }
        payload = _lt._build_login_payload("a@b.com", "s3cret", fields, "form", 0)
        assert payload is not None
        assert payload.get("csrf_token") == "tok123"

    def test_form_mode_missing_fields_falls_through_to_api_mode(self) -> None:
        """When form fields are incomplete, falls through to API mode permutations."""
        fields = {"email": "email"}  # missing password
        payload = _lt._build_login_payload("a@b.com", "s3cret", fields, "form", 0)
        # Should fall to API mode (first permutation: email/password, form-encoded)
        assert payload is not None
        assert payload.get("email") == "a@b.com"
        assert payload.get("password") == "s3cret"
        assert payload.get("_is_json") is False


class TestBuildLoginPayloadApiMode:
    """API mode — field name permutations with content type toggling."""

    def test_api_attempt_0_email_password_form(self) -> None:
        """Attempt 0: (email, password) with form-encoded."""
        payload = _lt._build_login_payload("admin@t.com", "pw", {}, "api", 0)
        assert payload is not None
        assert payload.get("email") == "admin@t.com"
        assert payload.get("password") == "pw"
        assert payload.get("_is_json") is False

    def test_api_attempt_1_email_password_json(self) -> None:
        """Attempt 1: (email, password) with JSON."""
        payload = _lt._build_login_payload("admin@t.com", "pw", {}, "api", 1)
        assert payload is not None
        assert payload.get("email") == "admin@t.com"
        assert payload.get("password") == "pw"
        assert payload.get("_is_json") is True

    def test_api_attempt_2_username_password_form(self) -> None:
        """Attempt 2: (username, password) with form-encoded."""
        payload = _lt._build_login_payload("admin", "pw", {}, "api", 2)
        assert payload is not None
        assert payload.get("username") == "admin"
        assert payload.get("password") == "pw"
        assert payload.get("_is_json") is False

    def test_api_attempt_3_username_password_json(self) -> None:
        """Attempt 3: (username, password) with JSON."""
        payload = _lt._build_login_payload("admin", "pw", {}, "api", 3)
        assert payload is not None
        assert payload.get("username") == "admin"
        assert payload.get("password") == "pw"
        assert payload.get("_is_json") is True

    def test_api_attempt_4_login_password_form(self) -> None:
        """Attempt 4: (login, password) with form-encoded."""
        payload = _lt._build_login_payload("admin", "pw", {}, "api", 4)
        assert payload is not None
        assert payload.get("login") == "admin"
        assert payload.get("password") == "pw"
        assert payload.get("_is_json") is False

    def test_api_attempt_5_login_password_json(self) -> None:
        """Attempt 5: (login, password) with JSON."""
        payload = _lt._build_login_payload("admin", "pw", {}, "api", 5)
        assert payload is not None
        assert payload.get("login") == "admin"
        assert payload.get("password") == "pw"
        assert payload.get("_is_json") is True

    def test_all_permutations_exhausted(self) -> None:
        """Returns None after all 14 (permutation, content_type) combinations."""
        # 7 permutations × 2 content types = 14 combinations
        for attempt in range(14):
            payload = _lt._build_login_payload("a", "b", {}, "api", attempt)
            assert payload is not None, f"Expected payload for attempt {attempt}"

        # Attempt 14 and beyond should return None
        assert _lt._build_login_payload("a", "b", {}, "api", 14) is None
        assert _lt._build_login_payload("a", "b", {}, "api", 100) is None

    def test_kebab_case_permutations(self) -> None:
        """Attempt 6: (email, pass) with form-encoded."""
        payload = _lt._build_login_payload("admin@t.com", "pw", {}, "api", 6)
        assert payload is not None
        assert payload.get("email") == "admin@t.com"
        assert payload.get("pass") == "pw"
        assert payload.get("_is_json") is False

    def test_attempt_7_email_pass_json(self) -> None:
        """Attempt 7: (email, pass) with JSON."""
        payload = _lt._build_login_payload("admin@t.com", "pw", {}, "api", 7)
        assert payload is not None
        assert payload.get("email") == "admin@t.com"
        assert payload.get("pass") == "pw"
        assert payload.get("_is_json") is True

    def test_last_permutation_user_password_json(self) -> None:
        """Last combination (attempt 13): user/password with JSON."""
        payload = _lt._build_login_payload("admin", "pw", {}, "api", 13)
        assert payload is not None
        assert payload.get("user") == "admin"
        assert payload.get("password") == "pw"
        assert payload.get("_is_json") is True


class TestBuildLoginPayloadIsJsonType:
    """``_is_json`` must be a Python boolean, never a string."""

    def test_is_json_is_boolean_form_mode_even(self) -> None:
        payload = _lt._build_login_payload(
            "a", "b", {"email": "e", "password": "p"}, "form", 0
        )
        assert payload is not None
        assert isinstance(payload.get("_is_json"), bool)
        assert payload["_is_json"] is False

    def test_is_json_is_boolean_form_mode_odd(self) -> None:
        """Form mode always sets ``_is_json`` to ``False``."""
        payload = _lt._build_login_payload(
            "a", "b", {"email": "e", "password": "p"}, "form", 1
        )
        assert payload is not None
        assert isinstance(payload.get("_is_json"), bool)
        assert payload["_is_json"] is False

    def test_is_json_is_boolean_api_even(self) -> None:
        payload = _lt._build_login_payload("a", "b", {}, "api", 0)
        assert payload is not None
        assert isinstance(payload.get("_is_json"), bool)
        assert payload["_is_json"] is False

    def test_is_json_is_boolean_api_odd(self) -> None:
        payload = _lt._build_login_payload("a", "b", {}, "api", 1)
        assert payload is not None
        assert isinstance(payload.get("_is_json"), bool)
        assert payload["_is_json"] is True
