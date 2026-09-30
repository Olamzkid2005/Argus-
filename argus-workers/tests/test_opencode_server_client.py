"""Tests for the local-OpenCode-server transport (opencode_server_client.py).

OpenCode's own gateways refuse direct calls made from this source tree
(HTTP 403 FreeTierError), but answer the same request when OpenCode itself makes
it — measured side by side in docs/DEMO-READINESS-PLAN.md, blocker B9. The
worker therefore asks a local ``opencode serve`` to make the call.

These tests pin the server contract, which is not obvious from the outside:

* the reply arrives in the message body, and the server answers 200 even when
  the provider call failed — the error is on ``message.info.error``;
* the prompt body has no ``temperature``/``max_tokens`` field
  (packages/sdk/openapi.json), so the client must not pretend to send them;
* the prompt must use the read-only ``plan`` agent: with the default ``build``
  agent a free-tier reply came back as a tool call rather than an answer, and a
  request with every tool denied was refused outright;
* a session is always deleted, including when the model call fails.
"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from opencode_server_client import (
    DEFAULT_TIMEOUT_SECONDS,
    OpencodeServerClient,
    OpencodeServerError,
)


def _resp(status_code: int, payload) -> MagicMock:
    """An httpx-Response-shaped mock carrying a JSON payload."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps(payload)
    resp.json.return_value = payload
    return resp


def _reply(text: str = "PONG", tokens=(11, 22), error: dict | None = None) -> dict:
    info: dict = {"id": "msg_1", "role": "assistant"}
    if tokens is not None:
        info["tokens"] = {"input": tokens[0], "output": tokens[1]}
    if error is not None:
        info["error"] = error
    parts = [{"type": "step-start"}]
    if text:
        parts.append({"type": "text", "text": text})
    return {"info": info, "parts": parts}


def _fake_http(handler) -> MagicMock:
    """An httpx.Client-shaped mock that routes calls through ``handler``."""
    fake = MagicMock()
    fake.__enter__ = MagicMock(return_value=fake)
    fake.__exit__ = MagicMock(return_value=False)

    def post(url, params=None, json=None):  # noqa: A002 - mirrors httpx
        return handler("POST", url, params, json)

    def request(method, url, params=None):
        return handler(method, url, params, None)

    fake.post.side_effect = post
    fake.request.side_effect = request
    return fake


def _happy_handler(calls: list):
    def handler(method, url, params, body):
        calls.append({"method": method, "url": url, "params": params, "body": body})
        if method == "DELETE":
            return _resp(200, {"id": "ses_1"})
        if url.endswith("/session"):
            return _resp(200, {"id": "ses_1"})
        return _resp(200, _reply())

    return handler


def _client(**overrides) -> OpencodeServerClient:
    kwargs = {
        "base_url": "http://127.0.0.1:4096",
        "model": "nemotron-3-ultra-free",
        "provider_id": "opencode",
        "directory": "/tmp/argus",
    }
    kwargs.update(overrides)
    return OpencodeServerClient(**kwargs)


class TestSuccessfulCall:
    def _run(self, messages=None):
        calls: list = []
        fake = _fake_http(_happy_handler(calls))
        with patch("httpx.Client", return_value=fake):
            result = _client().chat(
                messages if messages is not None else [{"role": "user", "content": "ping"}]
            )
        return result, calls

    def test_returns_the_assistant_text_and_tokens(self):
        result, _ = self._run()

        assert result.text == "PONG"
        assert result.input_tokens == 11
        assert result.output_tokens == 22
        # OpenCode bills the operator's account; Argus attributes nothing here.
        assert result.cost_usd == 0.0

    def test_session_lifecycle_and_prompt_shape(self):
        _, calls = self._run()

        assert [c["method"] for c in calls] == ["POST", "POST", "DELETE"]
        assert calls[0]["url"] == "http://127.0.0.1:4096/session"
        assert calls[1]["url"] == "http://127.0.0.1:4096/session/ses_1/message"
        assert calls[2]["url"] == "http://127.0.0.1:4096/session/ses_1"

    def test_prompt_names_the_model_and_the_read_only_agent(self):
        _, calls = self._run()

        body = calls[1]["body"]
        assert body["model"] == {
            "providerID": "opencode",
            "modelID": "nemotron-3-ultra-free",
        }
        # Measured: `build` answers planning prompts with tool calls; `plan` is
        # served and cannot modify anything.
        assert body["agent"] == "plan"
        assert body["parts"] == [{"type": "text", "text": "ping"}]

    def test_generation_settings_are_not_pretended(self):
        # The prompt body has no field for these (packages/sdk/openapi.json), so
        # sending them would be a silent lie about what reached the model.
        _, calls = self._run()

        body = calls[1]["body"]
        assert "temperature" not in body
        assert "max_tokens" not in body
        assert "response_format" not in body

    def test_directory_is_sent_as_a_query_parameter(self):
        _, calls = self._run()

        assert calls[0]["params"] == {"directory": "/tmp/argus"}
        assert calls[1]["params"] == {"directory": "/tmp/argus"}

        empty: list = []
        fake = _fake_http(_happy_handler(empty))
        with patch("httpx.Client", return_value=fake):
            _client(directory="").chat([{"role": "user", "content": "ping"}])
        assert empty[0]["params"] == {}

    def test_system_message_becomes_the_system_field(self):
        _, calls = self._run(
            [
                {"role": "system", "content": "You are terse."},
                {"role": "user", "content": "ping"},
            ]
        )

        body = calls[1]["body"]
        assert body["system"] == "You are terse."
        assert body["parts"] == [{"type": "text", "text": "ping"}]

    def test_history_roles_are_labelled_in_the_prompt(self):
        _, calls = self._run(
            [
                {"role": "system", "content": "Be terse."},
                {"role": "user", "content": "ping"},
                {"role": "assistant", "content": "pong"},
                {"role": "user", "content": "again"},
            ]
        )

        prompt = calls[1]["body"]["parts"][0]["text"]
        assert "[assistant] pong" in prompt
        assert prompt.endswith("again")


class TestFailures:
    def test_provider_error_on_the_message_is_raised(self):
        calls: list = []

        def handler(method, url, params, body):
            calls.append(method)
            if url.endswith("/session"):
                return _resp(200, {"id": "ses_1"})
            return _resp(
                200,
                _reply(
                    text="",
                    error={
                        "name": "APIError",
                        "data": {
                            "message": "OpenCode's free tier can only be used from within OpenCode",
                            "statusCode": 403,
                        },
                    },
                ),
            )

        with patch("httpx.Client", return_value=_fake_http(handler)):
            with pytest.raises(OpencodeServerError) as excinfo:
                _client().chat([{"role": "user", "content": "ping"}])

        assert "APIError" in str(excinfo.value)
        assert "free tier" in str(excinfo.value)
        # The server would have answered 200; only the message says otherwise.
        assert excinfo.value.retryable is False

    def test_session_is_deleted_even_when_the_call_fails(self):
        calls: list = []

        def handler(method, url, params, body):
            calls.append(method)
            if url.endswith("/session"):
                return _resp(200, {"id": "ses_1"})
            return _resp(
                200,
                _reply(text="", error={"name": "APIError", "data": {"message": "nope"}}),
            )

        with patch("httpx.Client", return_value=_fake_http(handler)):
            with pytest.raises(OpencodeServerError):
                _client().chat([{"role": "user", "content": "ping"}])

        assert calls == ["POST", "POST", "DELETE"]

    def test_reply_without_text_is_an_error(self):
        fake = _fake_http(
            lambda _method, url, _params, _body: (
                _resp(200, {"id": "ses_1"})
                if url.endswith("/session")
                else _resp(200, {"info": {}, "parts": [{"type": "step-start"}]})
            )
        )

        with patch("httpx.Client", return_value=fake):
            with pytest.raises(OpencodeServerError) as excinfo:
                _client().chat([{"role": "user", "content": "ping"}])

        assert "no text" in str(excinfo.value)
        assert "step-start" in str(excinfo.value)
        # An empty reply is the free tier's flakiest failure mode.
        assert excinfo.value.retryable is True

    def test_server_errors_are_classified_by_status(self):
        def failing(status):
            fake = _fake_http(
                lambda _method, url, _params, _body: (
                    _resp(200, {"id": "ses_1"})
                    if url.endswith("/session")
                    else _resp(status, {"error": "boom"})
                )
            )
            with patch("httpx.Client", return_value=fake):
                with pytest.raises(OpencodeServerError) as excinfo:
                    _client().chat([{"role": "user", "content": "ping"}])
            return excinfo.value

        assert failing(503).retryable is True
        assert failing(400).retryable is False

    def test_unreachable_server_is_retryable_and_says_how_to_start_it(self):
        def handler(method, url, params, body):
            raise httpx.ConnectError("connection refused")

        with patch("httpx.Client", return_value=_fake_http(handler)):
            with pytest.raises(OpencodeServerError) as excinfo:
                _client().chat([{"role": "user", "content": "ping"}])

        assert excinfo.value.retryable is True
        assert "opencode serve" in str(excinfo.value)

    def test_a_malformed_body_is_retryable(self):
        def handler(method, url, params, body):
            if url.endswith("/session"):
                bad = MagicMock()
                bad.status_code = 200
                bad.text = "<html>not json</html>"
                bad.json.side_effect = ValueError("Expecting value")
                return bad
            return _resp(200, _reply())

        with patch("httpx.Client", return_value=_fake_http(handler)):
            with pytest.raises(OpencodeServerError) as excinfo:
                _client().chat([{"role": "user", "content": "ping"}])

        assert excinfo.value.retryable is True


class TestConfiguration:
    def test_timeout_defaults_to_the_free_tier_budget(self):
        # A free-tier call takes 30-95s; the direct transports' 30s default
        # would abort calls that are still working.
        assert DEFAULT_TIMEOUT_SECONDS == 180
        assert _client().timeout == DEFAULT_TIMEOUT_SECONDS

    def test_base_url_trailing_slash_is_tolerated(self):
        client = _client(base_url="http://127.0.0.1:4096/")

        assert client.base_url == "http://127.0.0.1:4096"


def test_error_is_an_llm_unavailable_error():
    """Worker callers fall back to deterministic mode on this type."""
    from exceptions import LLMUnavailableError

    assert issubclass(OpencodeServerError, LLMUnavailableError)
