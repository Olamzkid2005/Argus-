"""
AuthContext — structured authentication state managed by the agent.

After register() or login() succeeds, the agent stores an AuthContext
instance. All tool wrappers read from this context to inject auth into
tool CLI arguments or pass the session object directly.

For Celery retry persistence: this object can be serialized to/from dict
(minus the live ``session`` which is re-established via login() on retry).
"""

from __future__ import annotations

from typing import Any

import requests


class AuthContext:
    """Structured authentication state managed by the agent.

    After register() or login() succeeds, the agent stores an AuthContext
    instance. All tool wrappers read from this context to inject auth into
    tool CLI arguments or pass the session object directly.

    Attributes:
        session: Live requests.Session (NOT serialized — re-established on retry).
        cookie_string: ``"name=value; name2=value2"`` format for --cookie CLI args.
        authorization: ``"Bearer eyJ..."`` or ``"Basic ..."`` for -H headers.
        csrf_token: CSRF token extracted from login form if present.
        email: Credentials used (for retry / re-registration).
        password: Credentials used (for retry / re-registration).
        register_url: Discovered registration endpoint.
        login_url: Discovered login endpoint.
    """

    def __init__(
        self,
        session: requests.Session | None = None,
        cookie_string: str | None = None,
        authorization: str | None = None,
        csrf_token: str | None = None,
        email: str | None = None,
        password: str | None = None,
        register_url: str | None = None,
        login_url: str | None = None,
    ) -> None:
        self.session = session
        self.cookie_string = cookie_string
        self.authorization = authorization
        self.csrf_token = csrf_token
        self.email = email
        self.password = password
        self.register_url = register_url
        self.login_url = login_url

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_authenticated(self) -> bool:
        """Check if we have a usable session."""
        return self.session is not None

    # ------------------------------------------------------------------
    # Serialization (for Celery retry persistence)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict — excludes the live ``session`` object.

        The session cannot be serialized; on retry the caller must
        re-establish it via login() using the stored credentials.
        """
        return {
            "cookie_string": self.cookie_string,
            "authorization": self.authorization,
            "csrf_token": self.csrf_token,
            "email": self.email,
            "password": self.password,
            "register_url": self.register_url,
            "login_url": self.login_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthContext:
        """Deserialize from dict.

        The ``session`` field is set to ``None`` — the caller must
        re-establish it via login() using the stored email/password.
        """
        return cls(
            cookie_string=data.get("cookie_string"),
            authorization=data.get("authorization"),
            csrf_token=data.get("csrf_token"),
            email=data.get("email"),
            password=data.get("password"),
            register_url=data.get("register_url"),
            login_url=data.get("login_url"),
        )

    def __repr__(self) -> str:
        authed = self.is_authenticated()
        email = self.email or "none"
        return f"AuthContext(authenticated={authed}, email={email})"
