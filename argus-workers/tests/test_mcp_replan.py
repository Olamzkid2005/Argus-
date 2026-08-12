"""Tests for MCPServer._replan LLM-branch wiring.

The LLM branch of ``ReActAgent.plan_next_action()`` is gated on a truthy
``recon_context``. Without one, the interactive replan loop silently falls
back to deterministic tool ordering and never actually reasons over the
accumulated observations. These tests lock in that ``_replan`` always
provides a recon_context (persisted when available, otherwise a minimal one
built from the session target).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agent.agent_action import AgentAction
from mcp_server import MCPServer, _canonical_phase_name


def _server() -> MCPServer:
    return MCPServer()


def _session(server: MCPServer, target: str = "https://example.com", phase: str = "scan"):
    session_id = server.session_store.create(target=target, phase=phase)
    return server.session_store.get(session_id)


def _mock_llm_available() -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    return mock_llm


class TestReplanReconContext:
    def test_replan_passes_recon_context(self):
        """plan_next_action must receive a non-None recon_context."""
        server = _server()
        session = _session(server)

        mock_action = AgentAction(
            tool="nuclei", arguments={}, reasoning="API found, scanning"
        )
        with patch("mcp_server.LLMClient", return_value=_mock_llm_available()):
            with patch(
                "agent.react_agent.ReActAgent.plan_next_action",
                return_value=mock_action,
            ) as mock_pna:
                result = server._replan(session)

        assert result["tool_order"] == ["nuclei"]
        call_kwargs = mock_pna.call_args.kwargs
        assert call_kwargs["recon_context"] is not None
        assert call_kwargs["recon_context"].target_url == "https://example.com"

    def test_replan_builds_minimal_context_without_engagement(self):
        """Sessions carry no engagement_id — the minimal-context fallback must engage."""
        server = _server()
        session = _session(server)
        assert getattr(session, "engagement_id", None) is None

        mock_action = AgentAction(tool="nuclei", arguments={}, reasoning="x")
        with patch("mcp_server.LLMClient", return_value=_mock_llm_available()):
            with patch(
                "agent.react_agent.ReActAgent.plan_next_action",
                return_value=mock_action,
            ) as mock_pna:
                server._replan(session)

        assert mock_pna.call_args.kwargs["recon_context"] is not None
        assert (
            mock_pna.call_args.kwargs["recon_context"].target_url
            == "https://example.com"
        )

    def test_replan_uses_persisted_recon_context_when_available(self):
        """When an engagement_id exists, the persisted ReconContext is preferred."""
        server = _server()
        session = _session(server)
        # Simulate a session that carries an engagement_id (e.g. set by caller)
        session.engagement_id = "550e8400-e29b-41d4-a716-446655440000"

        persisted = MagicMock()
        persisted.target_url = "https://persisted.example.com"

        mock_action = AgentAction(tool="nuclei", arguments={}, reasoning="x")
        with patch("mcp_server.LLMClient", return_value=_mock_llm_available()):
            with patch(
                "tasks.utils.load_recon_context", return_value=persisted
            ) as mock_load:
                with patch(
                    "agent.react_agent.ReActAgent.plan_next_action",
                    return_value=mock_action,
                ) as mock_pna:
                    server._replan(session)

        mock_load.assert_called_once_with(session.engagement_id)
        assert mock_pna.call_args.kwargs["recon_context"] is persisted

    def test_replan_real_llm_path_selects_registered_tool(self):
        """The REAL LLM branch works: a valid registered phase tool flows through.

        Exercises the actual plan_next_action/_call_llm_for_action path (not a
        patched plan_next_action): the mocked LLM selects a registered phase
        tool, which is validated against the registry and returned as
        tool_order. Without the tool-registration half of the fix, this would
        return done=True (LLM picks 'nuclei' → unknown in empty registry →
        deterministic fallback → nothing left).
        """
        server = _server()
        session = _session(server)  # phase="scan"

        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = json.dumps(
            {
                "tool": "nuclei",
                "arguments": {"target": "https://example.com"},
                "reasoning": "API discovered — scanning for vulnerabilities",
            }
        )

        with patch("mcp_server.LLMClient", return_value=mock_llm):
            result = server._replan(session)

        assert result.get("tool_order") == ["nuclei"]
        assert not result.get("done", False)

    def test_replan_still_deterministic_when_llm_unavailable(self):
        """No LLM → graceful done, same as before the fix."""
        server = _server()
        session = _session(server)

        mock_llm = MagicMock()
        mock_llm.is_available.return_value = False

        with patch("mcp_server.LLMClient", return_value=mock_llm):
            result = server._replan(session)

        assert result.get("done") is True
        assert "not available" in result.get("reasoning", "")

    def test_replan_handles_recon_load_failure(self):
        """A Redis/load failure must not break replan — minimal fallback engages."""
        server = _server()
        session = _session(server)
        session.engagement_id = "550e8400-e29b-41d4-a716-446655440000"

        mock_action = AgentAction(tool="nuclei", arguments={}, reasoning="x")
        with patch("mcp_server.LLMClient", return_value=_mock_llm_available()):
            with patch(
                "tasks.utils.load_recon_context", side_effect=RuntimeError("redis down")
            ):
                with patch(
                    "agent.react_agent.ReActAgent.plan_next_action",
                    return_value=mock_action,
                ) as mock_pna:
                    result = server._replan(session)

        assert result["tool_order"] == ["nuclei"]
        recon = mock_pna.call_args.kwargs["recon_context"]
        assert recon is not None
        assert recon.target_url == "https://example.com"

    def test_replan_degrades_gracefully_when_agent_creation_fails(self):
        """create_for_phase failure must not raise — bare agent + done path."""
        server = _server()
        session = _session(server)

        with patch(
            "agent.react_agent.ReActAgent.create_for_phase",
            side_effect=RuntimeError("tool_definitions broken"),
        ):
            with patch("mcp_server.LLMClient", return_value=_mock_llm_available()):
                # plan_next_action on the bare fallback agent returns None
                # (no tools registered) → done=True. No exception propagates.
                result = server._replan(session)

        assert result.get("done") is True

    def test_replan_normalizes_legacy_phase_names(self):
        """Legacy TS phase names must register tools under their canonical key."""
        assert _canonical_phase_name("vulnerability_scanning") == "scan"
        assert _canonical_phase_name("reconnaissance") == "recon"
        assert _canonical_phase_name("deep") == "deep_scan"
        assert _canonical_phase_name("scan") == "scan"

        server = _server()
        session = _session(server, phase="vulnerability_scanning")

        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = json.dumps(
            {
                "tool": "nuclei",
                "arguments": {"target": "https://example.com"},
                "reasoning": "scanning",
            }
        )

        with patch("mcp_server.LLMClient", return_value=mock_llm):
            result = server._replan(session)

        # With the legacy name normalized to "scan", the LLM's tool choice
        # validates against the registered scan-phase tools.
        assert result.get("tool_order") == ["nuclei"]
