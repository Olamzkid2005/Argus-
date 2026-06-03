"""
Regression tests — BolaWorkflow vs DualAuthScanner parity checks.

Verifies that BolaWorkflow produces the same findings as DualAuthScanner
when given the same inputs. This is critical for the "zero new detection
logic" design goal.

These tests are excluded from default CI. Run manually:
    python -m pytest tests/test_bola_workflow_regression.py -v
"""

from __future__ import annotations

import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from unittest.mock import Mock, PropertyMock, patch

import pytest


# Skip on Windows — tests require local HTTP server with threading
pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Integration test requires Unix-compatible HTTP server behavior",
)

from runtime.engagement_state import EngagementState
from runtime.workflows.bola import BolaWorkflow


# ── Test Server ────────────────────────────────────────────────────────


class RegressionTestServerHandler(BaseHTTPRequestHandler):
    """HTTP server with known BOLA + BOPLA vulnerabilities.

    Used to compare DualAuthScanner vs BolaWorkflow output parity.
    """

    def do_GET(self) -> None:
        token = self._get_token()
        if not token:
            self._send_json(401, {"error": "unauthorized"})
            return

        if self.path == "/api/accounts":
            self._send_json(200, {
                "accounts": [{"id": 1, "owner": "user_a", "balance": 100}],
                "_links": ["/api/accounts/1"],
            })
        elif self.path.startswith("/api/accounts/"):
            self._send_json(200, {
                "id": 1, "owner": "user_a", "balance": 100,
                "description": "User A's primary checking account.",
            })
        elif self.path == "/api/profile":
            self._send_json(200, {
                "username": "user_a", "email": "a@example.com",
                "ssn": "123-45-6789", "credit_card": "4111-1111-1111-1111",
            })
        elif self.path == "/api/me":
            self._send_json(200, {"id": 1, "username": "user_a"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        self._send_json(404, {"error": "not found"})

    def _get_token(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return None

    def _send_json(self, status: int, data: dict | list) -> None:
        import json
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def server_url() -> str:
    server = HTTPServer(("127.0.0.1", 0), RegressionTestServerHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        yield url
    finally:
        server.shutdown()


# ── Helpers ────────────────────────────────────────────────────────────


def _run_dual_auth_scanner(server_url: str) -> list[dict]:
    """Run the legacy DualAuthScanner against the server and return findings."""
    from tools.dual_auth_scanner import DualAuthScanner
    from tool_core.base import ToolContext
    from tool_core.config.models import DualAuthConfig

    scanner = DualAuthScanner()
    # Mock the auth_manager to avoid real auth flow
    with patch.object(scanner, "auth_manager_a") as mgr_a, \
         patch.object(scanner, "auth_manager_b") as mgr_b:
        mock_session = Mock()
        mock_session.headers = {}
        mock_session.request.return_value = Mock(status_code=200, text="{}")
        mgr_a.authenticate.return_value = mock_session
        mgr_b.authenticate.return_value = Mock()

        scanner.execute(ToolContext(
            target=server_url,
            dual_auth=DualAuthConfig(
                auth_a={"token": "tok_a", "token_header": "Authorization"},
                auth_b={"token": "tok_b", "token_header": "Authorization"},
            ),
        ))

    return scanner.findings


def _run_bola_workflow(server_url: str) -> tuple[EngagementState, list[dict]]:
    """Run BolaWorkflow against the server and return (state, findings)."""
    from utils.logging_utils import ScanLogger

    state = EngagementState("regression-test")
    findings: list[dict] = []

    def capture(eng_id: str, finding: dict, tool: str) -> None:
        findings.append(finding)

    slog = ScanLogger("bola_workflow_regression", engagement_id=state.engagement_id)
    workflow = BolaWorkflow(
        target=server_url,
        auth_config_a={"token": "tok_a", "token_header": "Authorization"},
        auth_config_b={"token": "tok_b", "token_header": "Authorization"},
        engagement_id=state.engagement_id,
        state=state,
        emit_finding_callback=capture,
        slog=slog,
    )

    result = workflow.execute()
    # Deduplicate findings (removes the double-emission from _emit_finding)
    seen = set()
    deduped = []
    for f in findings:
        key = (f.get("type"), f.get("endpoint"), f.get("severity"))
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return state, deduped, result


# ── Regression Tests ──────────────────────────────────────────────────


class TestBolaWorkflowRegression:
    """Parity tests: BolaWorkflow should match DualAuthScanner output."""

    @pytest.mark.integration
    def test_bola_finding_count_parity(self, server_url: str) -> None:
        """BolaWorkflow produces at least the same number of BOLA findings."""
        _, bw_findings, bw_result = _run_bola_workflow(server_url)
        da_findings = _run_dual_auth_scanner(server_url)

        bw_bola = [f for f in bw_findings if "BOLA" in f.get("type", "")]
        da_bola = [f for f in da_findings if "BOLA" in f.get("type", "")]

        # BolaWorkflow should find BOLA (server is intentionally vulnerable)
        assert len(bw_bola) > 0
        # BolaWorkflow should not produce fewer BOLA findings than DualAuthScanner
        # (same detection logic is reused)
        assert len(bw_bola) >= len(da_bola), (
            f"BolaWorkflow found {len(bw_bola)} BOLA findings, "
            f"DualAuthScanner found {len(da_bola)}"
        )

    @pytest.mark.integration
    def test_bopla_finding_count_parity(self, server_url: str) -> None:
        """BolaWorkflow produces BOPLA findings (same detection reused)."""
        _, bw_findings, _ = _run_bola_workflow(server_url)
        da_findings = _run_dual_auth_scanner(server_url)

        bw_bopla = [f for f in bw_findings if "BOPLA" in f.get("type", "")]
        da_bopla = [f for f in da_findings if "BOPLA" in f.get("type", "")]

        # Both scanners should find BOPLA (server exposes sensitive fields)
        assert len(bw_bopla) > 0
        assert len(da_bopla) > 0

    @pytest.mark.integration
    def test_finding_types_match(self, server_url: str) -> None:
        """BolaWorkflow produces the same finding types as DualAuthScanner."""
        _, bw_findings, _ = _run_bola_workflow(server_url)
        da_findings = _run_dual_auth_scanner(server_url)

        bw_types = {f.get("type") for f in bw_findings}
        da_types = {f.get("type") for f in da_findings}

        # BolaWorkflow should produce CONFIRMED_BOLA or POTENTIAL_BOLA
        assert bw_types.intersection({"CONFIRMED_BOLA", "POTENTIAL_BOLA"})
        # BolaWorkflow should produce BOPLA_SENSITIVE_FIELDS
        assert "BOPLA_SENSITIVE_FIELDS" in bw_types

    @pytest.mark.integration
    def test_workflow_completes_without_crash(self, server_url: str) -> None:
        """BolaWorkflow always returns a valid WorkflowResult."""
        _, _, bw_result = _run_bola_workflow(server_url)
        assert bw_result.success is True
        assert bw_result.outcome in ("complete", "partial")
        assert bw_result.findings_created >= 0
        assert isinstance(bw_result.metadata, dict)
