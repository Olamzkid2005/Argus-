"""Tests for tool auth injectors."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "auth_injectors",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "agent",
        "auth_injectors.py",
    ),
)
_ai = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ai)

_spec_ctx = importlib.util.spec_from_file_location(
    "auth_context",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "agent",
        "auth_context.py",
    ),
)
_ctx_mod = importlib.util.module_from_spec(_spec_ctx)
_spec_ctx.loader.exec_module(_ctx_mod)

import requests  # noqa: E402


def _make_ctx(cookie_str="session=abc123") -> _ctx_mod.AuthContext:
    session = requests.Session()
    if cookie_str:
        for pair in cookie_str.split("; "):
            if "=" in pair:
                name, value = pair.split("=", 1)
                session.cookies.set(name, value)
    return _ctx_mod.AuthContext(
        session=session,
        cookie_string=cookie_str,
        authorization="Bearer test-jwt-token",
    )


class TestAuthInjectors:
    """Tool-specific auth injection."""

    def test_inject_auth_no_context_returns_unchanged(self):
        args = ["-u", "http://test.com"]
        result = _ai.inject_auth("sqlmap", args, None)
        assert result == args

    def test_inject_auth_unknown_tool_returns_unchanged(self):
        ctx = _make_ctx()
        args = ["-u", "http://test.com"]
        result = _ai.inject_auth("unknown_tool", args, ctx)
        assert result == args

    def test_sqlmap_gets_cookie(self):
        ctx = _make_ctx()
        args = ["-u", "http://test.com"]
        result = _ai.inject_sqlmap_auth(args, ctx)
        assert "--cookie" in result
        assert "session=abc123" in result

    def test_sqlmap_no_duplicate_cookie(self):
        ctx = _make_ctx()
        args = ["-u", "http://test.com", "--cookie", "existing=1"]
        result = _ai.inject_sqlmap_auth(args, ctx)
        assert result == args  # Should not add another --cookie

    def test_nuclei_gets_header(self):
        ctx = _make_ctx()
        args = ["-u", "http://test.com"]
        result = _ai.inject_nuclei_auth(args, ctx)
        assert "-H" in result
        assert "Cookie: session=abc123" in result
        assert "Authorization: Bearer test-jwt-token" in result

    def test_nuclei_no_duplicate_header(self):
        ctx = _make_ctx()
        # Include both headers that would be injected
        args = [
            "-u",
            "http://test.com",
            "-H",
            "Cookie: session=abc123",
            "-H",
            "Authorization: Bearer test-jwt-token",
        ]
        result = _ai.inject_nuclei_auth(args, ctx)
        assert result == args

    def test_dalfox_gets_cookie_and_header(self):
        ctx = _make_ctx()
        args = ["-u", "http://test.com"]
        result = _ai.inject_dalfox_auth(args, ctx)
        assert "--cookie" in result
        assert "--header" in result

    def test_ffuf_gets_cookie(self):
        ctx = _make_ctx()
        args = ["-u", "http://test.com"]
        result = _ai.inject_ffuf_auth(args, ctx)
        assert "-b" in result
        assert "session=abc123" in result

    def test_nikto_gets_cookie(self):
        ctx = _make_ctx()
        args = ["-h", "http://test.com"]
        result = _ai.inject_nikto_auth(args, ctx)
        assert "-Cookie" in result

    def test_gospider_gets_cookie(self):
        ctx = _make_ctx()
        args = ["-u", "http://test.com"]
        result = _ai.inject_gospider_auth(args, ctx)
        assert "--cookie" in result

    def test_all_injectors_registered(self):
        expected = {"sqlmap", "dalfox", "nuclei", "ffuf", "nikto", "gospider"}
        assert set(_ai.TOOL_AUTH_INJECTORS.keys()) == expected

    def test_inject_auth_without_authorization(self):
        ctx = _make_ctx()
        ctx.authorization = None
        args = ["-u", "http://test.com"]
        result = _ai.inject_nuclei_auth(args, ctx)
        assert "-H" in result
        assert "Authorization" not in " ".join(result)


class TestHelperFunctions:
    """Internal helper function tests."""

    def test_has_cookie_flag_true(self):
        assert _ai._has_cookie_flag(["--cookie", "x"]) is True
        assert _ai._has_cookie_flag(["-b", "x"]) is True
        assert _ai._has_cookie_flag(["-Cookie", "x"]) is True

    def test_has_cookie_flag_false(self):
        assert _ai._has_cookie_flag(["-u", "http://test.com"]) is False
        assert _ai._has_cookie_flag(["-H", "Cookie: x"]) is False

    def test_has_header_flag_true(self):
        assert _ai._has_header_flag(["-H", "Cookie: abc"], "Cookie") is True
        assert (
            _ai._has_header_flag(["-H", "Authorization: Bearer x"], "Authorization")
            is True
        )

    def test_has_header_flag_false(self):
        assert _ai._has_header_flag(["-H", "Cookie: abc"], "Authorization") is False
        assert _ai._has_header_flag(["-u", "http://test.com"], "Cookie") is False
