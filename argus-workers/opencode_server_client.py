"""Make worker LLM calls through a local OpenCode server.

Why this exists: OpenCode's own gateways (the free tier and OpenCode Go) decide
whether to serve a request partly on *which client* is asking. A call from this
source tree gets::

    HTTP 403 {"type":"error","error":{"type":"FreeTierError",
              "message":"OpenCode's free tier can only be used from within OpenCode"}}

while an installed OpenCode answers the same request — measured side by side,
with byte-identical headers and bodies (docs/DEMO-READINESS-PLAN.md, blocker
B9). So the worker does not call the gateway at all: it asks the local OpenCode
server to make the call, and OpenCode does so with its own credentials.

The server API used here is the one OpenCode's own SDK is generated from:
create a session, prompt it, read the assistant's reply, delete the session.
Sessions are created per call so worker calls cannot leak context into one
another, and a session is always deleted, including on failure.

Two details are load-bearing, both measured against the live server:

* the prompt uses the read-only ``plan`` agent. With the default ``build``
  agent a free-tier reply came back as a tool call instead of an answer; with
  every tool denied the request was refused outright (HTTP 403 FreeTierError).
  ``plan`` is served and cannot modify anything.
* the reply is read from the message the server returns, not from an HTTP
  status: the server answers 200 even when the model call fails, putting the
  provider's error on ``message.info.error``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from exceptions import LLMUnavailableError
from llm_client import LLMResponse

logger = logging.getLogger(__name__)

#: A planner/worker call is usually 30-90s on OpenCode's free tier.
DEFAULT_TIMEOUT_SECONDS = 180

#: The read-only agent; see the module docstring for why this is not ``build``.
DEFAULT_AGENT = "plan"


class OpencodeServerError(LLMUnavailableError):
    """A call through the local OpenCode server could not be completed.

    ``retryable`` separates failures a retry can plausibly fix — an unreachable
    or slow server, an HTTP 5xx, an empty reply — from ones that will repeat
    identically: a provider refusal, a malformed request, a 4xx.
    """

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _split_messages(messages: list[dict]) -> tuple[str, str]:
    """Split chat messages into the server's (system, prompt) pair.

    The server takes one ``system`` string and a list of content parts, so the
    system role is separated out and everything else is rendered as one prompt
    with role labels. Worker callers send at most a system + user pair, so this
    keeps the transported text readable rather than lossy.
    """
    system_parts: list[str] = []
    body_parts: list[str] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        text = content if isinstance(content, str) else str(content)
        if role == "system":
            system_parts.append(text)
        elif role == "user":
            body_parts.append(text)
        else:
            body_parts.append(f"[{role}] {text}")
    return "\n\n".join(system_parts), "\n\n".join(body_parts)


class OpencodeServerClient:
    """Synchronous client for the prompt half of the local OpenCode server."""

    def __init__(
        self,
        base_url: str,
        model: str,
        provider_id: str,
        directory: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        agent: str = DEFAULT_AGENT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_id = provider_id
        self.directory = directory
        self.timeout = timeout
        self.agent = agent

    def _params(self) -> dict[str, str]:
        return {"directory": self.directory} if self.directory else {}

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: dict | None = None,
    ) -> LLMResponse:
        """Ask the server for a completion and return it as an LLMResponse.

        ``temperature``, ``max_tokens`` and ``response_format`` are accepted for
        signature compatibility with the direct transports. The prompt body has
        no field for any of them (packages/sdk/openapi.json), so they are not
        forwarded; ``response_format`` is not needed either, because the caller
        parses JSON out of the reply itself.

        Raises:
            OpencodeServerError: when the server, the session, or the model call
                fails — including the provider's own error, which the server
                reports on the message rather than as an HTTP status.
        """
        system, prompt = _split_messages(messages)
        params = self._params()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                session_id = self._create_session(client, params)
                try:
                    assistant = self._prompt(client, params, session_id, system, prompt)
                    self._raise_for_message_error(assistant)
                    text = self._text_of(assistant)
                    if not text:
                        raise OpencodeServerError(
                            "OpenCode returned no text for this prompt "
                            f"(parts: {self._shape_of(assistant)})",
                            # An empty reply is the free tier's most common
                            # flake; a retry is exactly what it needs.
                            retryable=True,
                        )
                    tokens = assistant.get("info", {}).get("tokens", {})
                    input_tokens = int(tokens.get("input") or 0)
                    output_tokens = int(tokens.get("output") or 0)
                    return LLMResponse(
                        text=text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        # OpenCode bills the operator's own account, so no cost
                        # is attributed to this call here.
                        cost_usd=0.0,
                    )
                finally:
                    self._delete_session(client, params, session_id)
        except (httpx.HTTPError, ValueError) as e:
            # Transport trouble or a non-JSON reply: both transient, so both
            # worth a retry. ValueError covers a malformed body from the server.
            raise OpencodeServerError(
                f"Local OpenCode server at {self.base_url} did not answer: {e}. "
                "Start it with `opencode serve`, or set OPENCODE_SERVER_URL.",
                retryable=True,
            ) from e

    # ── Server calls ────────────────────────────────────────────────

    def _create_session(self, client: httpx.Client, params: dict[str, str]) -> str:
        res = client.post(
            f"{self.base_url}/session",
            params=params,
            json={"title": "argus-worker"},
        )
        if res.status_code >= 400:
            raise OpencodeServerError(
                f"could not create an OpenCode session (HTTP {res.status_code}): "
                f"{res.text[:300]}",
                retryable=res.status_code >= 500,
            )
        session_id = res.json().get("id")
        if not session_id:
            raise OpencodeServerError("OpenCode session response had no id")
        return str(session_id)

    def _prompt(
        self,
        client: httpx.Client,
        params: dict[str, str],
        session_id: str,
        system: str,
        prompt: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": {"providerID": self.provider_id, "modelID": self.model},
            "agent": self.agent,
            "parts": [{"type": "text", "text": prompt}],
        }
        if system:
            body["system"] = system
        res = client.post(
            f"{self.base_url}/session/{session_id}/message",
            params=params,
            json=body,
        )
        if res.status_code >= 400:
            raise OpencodeServerError(
                f"OpenCode prompt failed (HTTP {res.status_code}): {res.text[:300]}",
                retryable=res.status_code >= 500,
            )
        return res.json()

    def _delete_session(
        self, client: httpx.Client, params: dict[str, str], session_id: str
    ) -> None:
        """Best-effort cleanup; a leaked session must not mask the real result."""
        try:
            client.request("DELETE", f"{self.base_url}/session/{session_id}", params=params)
        except httpx.HTTPError as e:  # pragma: no cover - cleanup path
            logger.debug("Could not delete OpenCode session %s: %s", session_id, e)

    # ── Reply parsing ───────────────────────────────────────────────

    @staticmethod
    def _text_of(message: dict[str, Any]) -> str:
        parts = message.get("parts") or []
        return "".join(
            str(p.get("text", ""))
            for p in parts
            if isinstance(p, dict) and p.get("type") == "text"
        ).strip()

    @staticmethod
    def _shape_of(message: dict[str, Any]) -> str:
        parts = message.get("parts") or []
        kinds = [str(p.get("type", "?")) for p in parts if isinstance(p, dict)]
        return ",".join(kinds) or "none"

    @staticmethod
    def _raise_for_message_error(message: dict[str, Any]) -> None:
        """Surface the provider's error; the server reports it on the message."""
        error = (message.get("info") or {}).get("error")
        if not error:
            return
        name = error.get("name", "error")
        detail = (error.get("data") or {}).get("message", "")
        # A refusal (expired free tier, missing subscription, bad key) repeats
        # identically; retrying it just burns another minute of quota.
        raise OpencodeServerError(
            f"OpenCode provider call failed: {name}{f': {detail}' if detail else ''}",
            retryable=False,
        )
