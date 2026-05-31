"""Tests for AuthContext dataclass."""

import importlib.util

# Load auth_context without triggering agent __init__.py
_spec = importlib.util.spec_from_file_location(
    "auth_context", "agent/auth_context.py",
)
_auth_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_auth_mod)

import requests


class TestAuthContext:
    """AuthContext creation and serialization."""

    def test_defaults(self):
        ctx = _auth_mod.AuthContext()
        assert ctx.session is None
        assert ctx.cookie_string is None
        assert ctx.authorization is None
        assert ctx.email is None
        assert ctx.password is None
        assert ctx.is_authenticated() is False

    def test_with_session(self):
        session = requests.Session()
        ctx = _auth_mod.AuthContext(
            session=session,
            email="test@test.com",
            cookie_string="abc=123",
        )
        assert ctx.is_authenticated() is True
        assert ctx.email == "test@test.com"
        assert ctx.cookie_string == "abc=123"

    def test_serialization_round_trip(self):
        ctx = _auth_mod.AuthContext(
            session=requests.Session(),
            email="a@b.com",
            password="secret",
            cookie_string="x=y",
            authorization="Bearer eyJ",
            csrf_token="csrf123",
            register_url="/register",
            login_url="/login",
        )
        data = ctx.to_dict()
        assert data["email"] == "a@b.com"
        assert data["password"] == "secret"
        assert "session" not in data  # Live session excluded

        # Deserialize
        ctx2 = _auth_mod.AuthContext.from_dict(data)
        assert ctx2.email == "a@b.com"
        assert ctx2.password == "secret"
        assert ctx2.cookie_string == "x=y"
        assert ctx2.authorization == "Bearer eyJ"
        assert ctx2.csrf_token == "csrf123"
        assert ctx2.register_url == "/register"
        assert ctx2.login_url == "/login"
        assert ctx2.session is None  # Session not restored
        assert ctx2.is_authenticated() is False

    def test_partial_serialization(self):
        """Only set fields should be serialized."""
        ctx = _auth_mod.AuthContext(email="only@email.com")
        data = ctx.to_dict()
        assert data["email"] == "only@email.com"
        assert data["password"] is None
        assert data["cookie_string"] is None

    def test_repr(self):
        ctx = _auth_mod.AuthContext(email="test@test.com")
        rep = repr(ctx)
        assert "test@test.com" in rep
        assert "authenticated=False" in rep
