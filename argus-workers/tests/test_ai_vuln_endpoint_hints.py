"""The ``extra.ai_endpoints`` hint must reach a login-gated assistant.

The AI scanner previously only probed its anonymous default paths. A target
whose assistant lives behind login therefore looked like it had no AI surface.
These tests use a local stub that:

* answers 401 on /api/ai/chat unless ``Authorization: Bearer <token>`` is sent,
* logs in via POST /login and returns that token,
* returns an assistant reply containing the system prompt plus model/context
  metadata, and
* records every path and Authorization header it receives.

They assert the configured hint is the endpoint probed (not the defaults), the
engagement's credentials are attached, and the expected AI findings are emitted.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tool_core.base import ToolContext
from tools.ai_vuln_scanner import AIVulnScanner

TOKEN = "stub-token"


class _Handler(BaseHTTPRequestHandler):
    requests_seen = []

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.requests_seen.append((self.path, self.headers.get("Authorization", "")))
        if self.path.startswith("/api/ai/"):
            self._send(405, {"error": "method not allowed"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        auth = self.headers.get("Authorization", "")
        self.requests_seen.append((self.path, auth))

        if self.path == "/login":
            if body.get("username") == "alice" and body.get("password") == "pw":
                self._send(200, {"status": "ok", "token": TOKEN})
            else:
                self._send(401, {"error": "bad credentials"})
            return

        if self.path == "/api/ai/chat":
            if auth != f"Bearer {TOKEN}":
                self._send(401, {"error": "authentication required"})
                return
            self._send(
                200,
                {
                    "ai_response": {
                        "response": (
                            "My system prompt: You are the VulnBank support "
                            "assistant with database access."
                        ),
                        "model": "stub-model",
                        "api_used": "stub-provider",
                        "database_accessed": True,
                        "context_included": True,
                    },
                    "status": "success",
                },
            )
            return

        if self.path == "/api/ai/support-chat":
            # Deliberately answers without any session.
            self._send(200, {"ai_response": {"response": "hello"}})
            return

        self._send(404, {"error": "not found"})


@pytest.fixture()
def stub():
    _Handler.requests_seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_hint_with_token_probes_gated_endpoint_authenticated(stub):
    ctx = ToolContext(target=stub, timeout=5)
    ctx._ai_endpoints = '["/api/ai/chat"]'
    ctx._token = TOKEN

    result = AIVulnScanner(timeout=5, rate_limit=0).execute(ctx)
    types = {f["type"] for f in result.findings}

    # The configured path was probed with the credential, not anonymously.
    # One empty header is expected: the broken-authorization probe is
    # deliberately anonymous, and the gated endpoint rejects it with 401.
    chat_calls = [auth for path, auth in _Handler.requests_seen if path == "/api/ai/chat"]
    assert chat_calls.count(f"Bearer {TOKEN}") >= 2
    assert "" in chat_calls
    # The anonymous defaults were not substituted for the hint.
    assert not any(path == "/api/chat" for path, _ in _Handler.requests_seen)

    assert "AI_SYSTEM_INFO_EXPOSURE" in types
    assert "PROMPT_INJECTION" in types or "AI_INFORMATION_DISCLOSURE" in types
    system_info = [f for f in result.findings if f["type"] == "AI_SYSTEM_INFO_EXPOSURE"]
    assert system_info[0]["evidence"]["authenticated_probe"] is True


def test_hint_with_password_logs_in_then_probes_authenticated(stub):
    ctx = ToolContext(target=stub, timeout=5)
    ctx._ai_endpoints = ["/api/ai/chat"]
    ctx._username = "alice"
    ctx._password = "pw"

    result = AIVulnScanner(timeout=5, rate_limit=0).execute(ctx)
    paths = [path for path, _ in _Handler.requests_seen]

    assert "/login" in paths
    chat_calls = [auth for path, auth in _Handler.requests_seen if path == "/api/ai/chat"]
    assert chat_calls.count(f"Bearer {TOKEN}") >= 2
    assert any(f["type"].startswith("AI_") for f in result.findings)


def test_gated_endpoint_without_credentials_yields_no_ai_finding(stub):
    ctx = ToolContext(target=stub, timeout=5)
    ctx._ai_endpoints = '["/api/ai/chat"]'

    result = AIVulnScanner(timeout=5, rate_limit=0).execute(ctx)

    assert result.findings == []
    # It was still the hinted path that got probed (and rejected).
    assert any(path == "/api/ai/chat" for path, _ in _Handler.requests_seen)


def test_authorization_probe_is_sent_without_the_engagement_token(stub):
    ctx = ToolContext(target=stub, timeout=5)
    ctx._ai_endpoints = '["/api/ai/support-chat"]'
    ctx._token = TOKEN

    result = AIVulnScanner(timeout=5, rate_limit=0).execute(ctx)
    types = {f["type"] for f in result.findings}

    assert "AI_BROKEN_AUTHORIZATION" in types
    auths = [auth for path, auth in _Handler.requests_seen if path == "/api/ai/support-chat"]
    assert "" in auths  # the authz probe itself carried no Authorization header
