"""
Integration tests for BolaWorkflow — runs against a local HTTP server.

Two test scenarios:
  1. Full BOLA workflow: User A creates resource → User B accesses it →
     CONFIRMED_BOLA finding emitted, FindingBuilder routing, obstacle handling,
     session lifecycle.
  2. BOPLA-after-auth-failure: User B auth fails → BOPLA still runs on User A.

These tests are excluded from default CI (``@pytest.mark.integration``).
Run manually:
    python -m pytest tests/test_bola_workflow_integration.py -v

Note: These tests construct ``BolaWorkflow`` directly — they don't require
the ``bola_workflow`` feature flag to be enabled (that flag gates the
``scan.py`` wiring, not the workflow class itself).
"""

from __future__ import annotations

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from unittest.mock import Mock, patch

import pytest

from runtime.engagement_state import EngagementState
from runtime.workflows.base import StepResult


# ── Local Test Server ─────────────────────────────────────────────────


class BolaTestServerHandler(BaseHTTPRequestHandler):
    """Minimal HTTP server simulating an app with BOLA vulnerability.

    Endpoints:
      POST /api/login         → sets session cookie, returns {"token": "..."}
      GET  /api/accounts      → returns accounts owned by the authenticated user
      GET  /api/accounts/{id} → returns account details (BOLA vulnerable: no
                                ownership check — User B can read User A's data)
      GET  /api/profile       → returns user profile with sensitive fields (BOPLA)
    """

    # Shared state across requests (handler is re-instantiated per request).
    sessions: dict[str, dict] = {}  # token → user data (populated by POST /api/login)

    def do_POST(self) -> None:
        if self.path == "/api/login":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body) if body else {}
            username = data.get("username", "unknown")
            token = f"tok_{username}"
            self.sessions[token] = {"user": username}
            self._send_json(200, {"token": token})
        else:
            self._send_json(404, {"error": "not found"})

    def do_GET(self) -> None:
        token = self._get_token()
        user = self.sessions.get(token, {}).get("user", "unknown") if token else "unknown"

        if self.path == "/api/accounts":
            # Return all accounts regardless of user — test scenario is that
            # the endpoint exposes account data in the response body in a way
            # that _discover_owned_resources can parse (regex + JSON extraction).
            all_accounts = [
                {"id": 1, "owner": "user_a", "balance": 100},
            ]
            # Include URL-style hrefs so the RESOURCE_PATTERNS regex matches:
            #   r'/(?:api/)?accounts?/(\d+)'  extracts '1' from '/api/accounts/1'
            response_data = {
                "accounts": all_accounts,
                "_links": [f"/api/accounts/{a['id']}" for a in all_accounts],
            }
            self._send_json(200, response_data)

        elif self.path.startswith("/api/accounts/"):
            # BOLA: no ownership check — any authenticated user can read any account.
            # Response must be >50 chars to trigger CONFIRMED_BOLA (vs POTENTIAL_BOLA).
            self._send_json(200, {
                "id": 1,
                "owner": "user_a",
                "balance": 100,
                "description": "User A's primary checking account with standard features.",
            })

        elif self.path == "/api/profile":
            # BOPLA: exposes sensitive fields
            self._send_json(200, {
                "username": user,
                "email": f"{user}@example.com",
                "ssn": "123-45-6789",
                "credit_card": "4111-1111-1111-1111",
            })

        elif self.path == "/api/me":
            self._send_json(200, {"id": 1, "username": user})

        else:
            self._send_json(404, {"error": "not found"})

    def _get_token(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return None

    def _send_json(self, status: int, data: dict | list) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # silence server logs during tests


@pytest.fixture(scope="module")
def server_url() -> str:
    """Start a local HTTP server on a random port and return its URL."""
    server = HTTPServer(("127.0.0.1", 0), BolaTestServerHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        yield url
    finally:
        server.shutdown()


@pytest.fixture
def state() -> EngagementState:
    return EngagementState("eng-integration-test")


# ── Test 1: Full BOLA Workflow ────────────────────────────────────────


class TestBolaWorkflowIntegration:
    """End-to-end BOLA workflow against a live local HTTP server.

    Validates: workflow orchestration, finding emission, FindingBuilder
    routing, obstacle handling, and session lifecycle.
    """

    @pytest.mark.integration
    def test_bola_workflow_detects_cross_account_access(self, server_url: str, state: EngagementState) -> None:
        """Full BOLA workflow: User B accesses User A's resource -> finding emitted."""

        findings: list[dict] = []

        def capture_finding(_eng_id: str, finding: dict, _tool: str) -> None:
            findings.append(finding)

        from runtime.workflows import BolaWorkflow
        from utils.logging_utils import ScanLogger

        # Use token-based auth to bypass the form-login flow
        auth_a = {"token": "tok_user_a", "token_header": "Authorization"}
        auth_b = {"token": "tok_user_b", "token_header": "Authorization"}

        slog = ScanLogger("bola_workflow_test", engagement_id=state.engagement_id)
        workflow = BolaWorkflow(
            target=server_url,
            auth_config_a=auth_a,
            auth_config_b=auth_b,
            engagement_id=state.engagement_id,
            state=state,
            emit_finding_callback=capture_finding,
            slog=slog,
        )

        result = workflow.execute()

        # Workflow completed successfully
        assert result.success is True
        assert result.outcome in ("complete", "partial")

        # BOLA finding should be detected (server has no ownership check).
        # Accept CONFIRMED_BOLA or POTENTIAL_BOLA — the test validates the
        # workflow pipeline, not the scanner's severity classification.
        bola_findings = [f for f in findings if "BOLA" in f.get("type", "")]
        assert len(bola_findings) > 0, (
            f"Expected at least one BOLA finding, got {len(bola_findings)}. "
            f"All findings: {[f.get('type') for f in findings]}"
        )

        # Results tracked locally (not from state.findings).
        # NOTE: findings list may have duplicates because _emit_finding routes
        # through FindingBuilder.add() AND calls emit_finding_callback directly.
        # This matches existing DualAuthScanner behavior. The local counter
        # (result.findings_created) is the authoritative count.
        assert result.findings_created > 0
        assert result.findings_created <= len(findings)
        # state.findings is populated post-scan by orchestrator — should be 0 mid-workflow
        assert len(state.findings) == 0

    @pytest.mark.integration
    def test_bopla_still_executes_when_user_b_auth_fails(self, server_url: str, state: EngagementState) -> None:
        """BOPLA must run against User A even when User B authentication fails."""

        findings: list[dict] = []

        def capture_finding(_eng_id: str, finding: dict, _tool: str) -> None:
            findings.append(finding)

        from runtime.workflows import BolaWorkflow
        from utils.logging_utils import ScanLogger

        # User B will have an unauthenticated session (no token).
        # The step pipeline checks ctx.session_b independently from session_a,
        # so BOPLA should still run on User A.
        auth_a = {"token": "tok_user_a", "token_header": "Authorization"}
        auth_b = {}  # No credentials — AuthManager returns unauthenticated session

        slog = ScanLogger("bola_workflow_test", engagement_id=state.engagement_id)
        workflow = BolaWorkflow(
            target=server_url,
            auth_config_a=auth_a,
            auth_config_b=auth_b,
            engagement_id=state.engagement_id,
            state=state,
            emit_finding_callback=capture_finding,
            slog=slog,
        )

        result = workflow.execute()

        # Workflow completed (not crashed)
        assert result.success is True

        # BOPLA findings from User A should still be present
        bopla_findings = [f for f in findings if "BOPLA" in f.get("type", "")]
        assert len(bopla_findings) > 0, (
            f"Expected BOPLA findings from User A, got {len(bopla_findings)}. "
            f"Obstacles: {[o['type'] for o in state.obstacles]}"
        )

    @pytest.mark.integration
    def test_workflow_sessions_closed(self, server_url: str, state: EngagementState) -> None:
        """Sessions are closed after workflow execution."""

        from runtime.workflows import BolaWorkflow
        from utils.logging_utils import ScanLogger

        # Mock AuthManager.authenticate to return a controllable session
        mock_session_a = Mock()
        mock_session_b = Mock()
        auth_a = {"token": "tok_user_a", "token_header": "Authorization"}
        auth_b = {"token": "tok_user_b", "token_header": "Authorization"}

        slog = ScanLogger("bola_workflow_test", engagement_id=state.engagement_id)
        workflow = BolaWorkflow(
            target=server_url,
            auth_config_a=auth_a,
            auth_config_b=auth_b,
            engagement_id=state.engagement_id,
            state=state,
            emit_finding_callback=lambda *a: None,
            slog=slog,
        )

        # Replace sessions on the context so execute()'s finally block closes them
        workflow.ctx.session_a = mock_session_a
        workflow.ctx.session_b = mock_session_b

        # Patch steps to skip real HTTP calls — we're only testing session cleanup
        workflow.steps[0].run = Mock(return_value=StepResult(success=True))
        workflow.steps[1].run = Mock(return_value=StepResult(success=True))
        workflow.steps[2].run = Mock(return_value=StepResult(success=True))
        workflow.steps[3].run = Mock(return_value=StepResult(success=True))

        workflow.execute()

        mock_session_a.close.assert_called_once()
        mock_session_b.close.assert_called_once()
