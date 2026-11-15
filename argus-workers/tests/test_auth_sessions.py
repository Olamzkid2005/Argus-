"""Tests for identity-scoped auth sessions and secret hygiene (Stage 5.2)."""

import pytest

from agent.auth_context import AuthContext
from agent.auth_sessions import (
    REDACTED,
    AuthExpiredError,
    AuthSessionError,
    EngagementAuthSessions,
    collects_secrets,
    redact_arguments,
    redact_text,
)


def make_context(email: str, cookie: str, authorization: str | None = None) -> AuthContext:
    return AuthContext(
        session=object(),
        cookie_string=cookie,
        authorization=authorization,
        email=email,
        password=f"{email}-password",
        login_url="https://app.example.com/login",
    )


@pytest.fixture
def sessions():
    return EngagementAuthSessions()


class TestIdentityScoping:
    def test_two_identities_keep_separate_sessions(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=alice"))
        sessions.store("eng-1", "bob", make_context("bob@example.com", "sid=bob"))

        assert sessions.headers_for("eng-1", "alice")["Cookie"] == "sid=alice"
        assert sessions.headers_for("eng-1", "bob")["Cookie"] == "sid=bob"
        assert sessions.identities("eng-1") == ["alice", "bob"]

    def test_context_for_returns_only_the_named_identity(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=alice"))
        sessions.store("eng-1", "bob", make_context("bob@example.com", "sid=bob"))
        assert sessions.context_for("eng-1", "alice").cookie_string == "sid=alice"
        assert sessions.context_for("eng-1", "nobody") is None

    def test_an_unknown_identity_never_receives_another_user_s_session(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=alice"))
        with pytest.raises(AuthSessionError, match="no authentication session"):
            sessions.headers_for("eng-1", "mallory")

    def test_sessions_are_scoped_by_engagement(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=one"))
        sessions.store("eng-2", "alice", make_context("alice@example.com", "sid=two"))
        assert sessions.headers_for("eng-1", "alice")["Cookie"] == "sid=one"
        assert sessions.headers_for("eng-2", "alice")["Cookie"] == "sid=two"

    def test_identity_is_required(self, sessions):
        with pytest.raises(AuthSessionError, match="scoped to an identity"):
            sessions.store("eng-1", "", make_context("alice@example.com", "sid=alice"))

    def test_snapshot_contains_no_tokens_or_credentials(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=alice", "Bearer abc"))
        snapshot = sessions.snapshot("eng-1")
        assert snapshot[0]["identity"] == "alice"
        assert "sid=alice" not in str(snapshot)
        assert "Bearer abc" not in str(snapshot)
        assert "password" not in str(snapshot).lower()


class TestExpiryAndRefresh:
    def test_a_valid_session_is_verified_and_timestamped(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=alice"))
        session = sessions.verify("eng-1", "alice", lambda _ctx: True)
        assert session.expired is False
        assert session.last_verified_at

    def test_one_refresh_is_attempted_after_expiry(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=old"))
        state = {"valid": False}

        def check(ctx):
            return state["valid"]

        def refresh(session):
            state["valid"] = True
            return make_context("alice@example.com", "sid=new")

        session = sessions.verify("eng-1", "alice", check, refresh)
        assert session.context.cookie_string == "sid=new"
        assert session.refresh_count == 1
        assert session.expired is False
        assert sessions.headers_for("eng-1", "alice")["Cookie"] == "sid=new"

    def test_a_failed_refresh_raises_a_clear_auth_error(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=old"))
        with pytest.raises(AuthExpiredError, match="pause for operator credentials"):
            sessions.verify(
                "eng-1",
                "alice",
                lambda _ctx: False,
                lambda _session: make_context("alice@example.com", "sid=still-bad"),
            )

    def test_only_one_refresh_is_allowed(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=old"))
        state = {"calls": 0}

        def refresh(session):
            state["calls"] += 1
            return make_context("alice@example.com", "sid=new")

        with pytest.raises(AuthExpiredError, match="single allowed refresh"):
            sessions.verify("eng-1", "alice", lambda _ctx: False, refresh)
        assert state["calls"] == 1
        assert sessions.get("eng-1", "alice").expired is True

    def test_expired_session_headers_are_not_handed_out(self, sessions):
        sessions.store("eng-1", "alice", make_context("alice@example.com", "sid=alice"))
        sessions.invalidate("eng-1", "alice")
        with pytest.raises(AuthExpiredError, match="marked expired"):
            sessions.headers_for("eng-1", "alice")


class TestSecretHygiene:
    def test_redact_arguments_removes_credentials_and_tokens(self):
        redacted = redact_arguments(
            {
                "target": "https://app.example.com",
                "password": "hunter2",
                "headers": {"Authorization": "Bearer abc"},
                "nested": [{"api_key": "k-1"}, "safe"],
            }
        )
        assert redacted["target"] == "https://app.example.com"
        assert redacted["password"] == REDACTED
        assert redacted["headers"]["Authorization"] == REDACTED
        assert redacted["nested"][0]["api_key"] == REDACTED
        assert redacted["nested"][1] == "safe"
        assert "hunter2" not in str(redacted)

    def test_redact_text_removes_known_secret_values(self):
        assert redact_text("cookie sid=abc used", ["sid=abc"]) == f"cookie {REDACTED} used"

    def test_collects_secrets_detects_leaks(self):
        assert collects_secrets("password=hunter2", ["hunter2"]) is True
        assert collects_secrets("nothing here", ["hunter2"]) is False
