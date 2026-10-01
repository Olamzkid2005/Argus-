"""Tests for the MCP path's plan generation (`MCPServer._agentic_plan`).

`handle_agent_init` used to re-order the driver's own pipeline and present the
result as the phase plan: the selection prompt, the recon context and the
decision log all existed, but the engine was never asked. These tests lock in
the new contract — the engine chooses tools, each choice is recorded with its
own provenance, and a stopped engine falls back to a labelled deterministic
remainder instead of silently shrinking the phase.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import mcp_server
from mcp_server import MCPServer, ToolDefinition

ENGAGEMENT = "ENG-demo-1"


def _server() -> MCPServer:
    server = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
    for name in ("nuclei", "nmap", "ffuf"):
        server.register_tool(ToolDefinition(name=name, command=name))
    return server


def _session(server: MCPServer, engagement_id: str = ENGAGEMENT):
    session_id = server.session_store.create(
        target="https://example.com",
        phase="scan",
        engagement_id=engagement_id,
    )
    return server.session_store.get(session_id)


def _llm(*tools: str, reasoning: str = "engine reason") -> MagicMock:
    """An available LLM that selects `tools`, then repeats the last one.

    A real model asked for another tool after it has nothing new to propose
    repeats itself; the tried-tool rejection is what stops the loop.
    """
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    replies = [
        json.dumps(
            {
                "tool": tool,
                "arguments": {"target": "https://example.com"},
                "reasoning": reasoning,
            }
        )
        for tool in tools
    ]
    mock_llm.chat_sync.side_effect = replies + [replies[-1]] * 10
    return mock_llm


def _unavailable_llm() -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = False
    return mock_llm


def _hypotheses_patch():
    """Keep `handle_agent_init` off the real hypotheses table."""
    mock_repo = MagicMock()
    mock_repo.return_value.get_by_engagement.return_value = []
    return patch(
        "database.repositories.hypothesis_repository.HypothesisRepository",
        mock_repo,
    )


class TestAgenticPlan:
    def test_engine_choices_are_recorded_with_their_provenance(self):
        server = _server()
        session = _session(server)
        repo = MagicMock()
        pipeline = [{"tool": "nuclei"}, {"tool": "nmap"}]

        with patch("mcp_server.LLMClient", return_value=_llm("nuclei", "nmap")), patch(
            "mcp_server._agent_decision_repo", return_value=repo
        ):
            plan = server._agentic_plan(session, pipeline)

        assert plan is not None
        assert plan["tool_order"] == ["nuclei", "nmap"]
        assert plan["sources"] == ["llm", "llm"]
        assert plan["source"] == "llm"
        assert "engine reason" in plan["reasoning"]

        calls = repo.log_decision.call_args_list
        assert [call.kwargs["tool_selected"] for call in calls] == ["nuclei", "nmap"]
        assert [call.kwargs["was_fallback"] for call in calls] == [False, False]
        assert {call.kwargs["engagement_id"] for call in calls} == {ENGAGEMENT}

    def test_stopped_engine_falls_back_to_the_labelled_pipeline_remainder(self):
        server = _server()
        session = _session(server)
        repo = MagicMock()
        pipeline = [{"tool": "nuclei"}, {"tool": "nmap"}, {"tool": "ffuf"}]

        with patch("mcp_server.LLMClient", return_value=_llm("nuclei")), patch(
            "mcp_server._agent_decision_repo", return_value=repo
        ):
            plan = server._agentic_plan(session, pipeline)

        assert plan["tool_order"] == ["nuclei", "nmap", "ffuf"]
        assert plan["sources"] == ["llm", "deterministic", "deterministic"]
        # Only the engine's own choice is recorded here; the deterministic
        # remainder is recorded as it is consumed.
        assert repo.log_decision.call_count == 1

    def test_a_slow_provider_cannot_chain_past_the_plan_budget(self, monkeypatch):
        """A provider that never answers must not hold `agent_init` open.

        Each choice is an LLM call the driver blocks on, so the loop is bounded
        by wall clock as well as by tool count: whatever the budget leaves
        unchosen runs as the labelled deterministic remainder. This is what
        keeps a slow free-tier model from timing the phase out entirely.
        """
        server = _server()
        session = _session(server)
        repo = MagicMock()
        pipeline = [{"tool": "nuclei"}, {"tool": "nmap"}, {"tool": "ffuf"}]
        # Shorter than a single call, so the second iteration must stop.
        monkeypatch.setattr(mcp_server, "_PLAN_BUDGET_SECONDS", 0.05)

        slow_llm = MagicMock()
        slow_llm.is_available.return_value = True

        def _slow_reply(*_args, **_kwargs):
            time.sleep(0.1)
            return json.dumps(
                {
                    "tool": "nuclei",
                    "arguments": {"target": "https://example.com"},
                    "reasoning": "engine reason",
                }
            )

        slow_llm.chat_sync.side_effect = _slow_reply

        with patch("mcp_server.LLMClient", return_value=slow_llm), patch(
            "mcp_server._agent_decision_repo", return_value=repo
        ):
            plan = server._agentic_plan(session, pipeline)

        assert slow_llm.chat_sync.call_count == 1
        assert plan["tool_order"] == ["nuclei", "nmap", "ffuf"]
        assert plan["sources"] == ["llm", "deterministic", "deterministic"]
        assert repo.log_decision.call_count == 1

    def test_no_llm_returns_none_without_calling_the_provider(self):
        server = _server()
        session = _session(server)
        mock_llm = _unavailable_llm()

        with patch("mcp_server.LLMClient", return_value=mock_llm):
            plan = server._agentic_plan(session, [{"tool": "nuclei"}])

        assert plan is None
        assert mock_llm.chat_sync.call_count == 0

    def test_an_engine_that_cannot_answer_returns_none(self):
        server = _server()
        session = _session(server)
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = "not json at all"

        with patch("mcp_server.LLMClient", return_value=mock_llm):
            plan = server._agentic_plan(session, [{"tool": "nuclei"}])

        assert plan is None


class TestPlanProvenanceThroughInitAndNext:
    def test_engine_chosen_step_reads_as_engine_chosen(self):
        server = _server()
        repo = MagicMock()

        with patch("mcp_server.LLMClient", return_value=_llm("nuclei")), patch(
            "mcp_server._agent_decision_repo", return_value=repo
        ), _hypotheses_patch():
            init = server.handle_agent_init(
                {
                    "target": "https://example.com",
                    "phase": "scan",
                    "pipeline": [{"tool": "nuclei"}, {"tool": "nmap"}],
                    "engagementId": ENGAGEMENT,
                }
            )
            step1 = server.handle_agent_next({"session_id": init["session_id"]})
            step2 = server.handle_agent_next({"session_id": init["session_id"]})

        assert init["plan"] == ["nuclei", "nmap"]
        assert step1["tool"] == "nuclei"
        assert step1["reasoning"] == "Engine-chosen plan step"
        assert step2["tool"] == "nmap"
        assert step2["reasoning"] == "Deterministic plan step"

        calls = repo.log_decision.call_args_list
        assert [call.kwargs["tool_selected"] for call in calls] == ["nuclei", "nmap"]
        assert [call.kwargs["was_fallback"] for call in calls] == [False, True]

    def test_deterministic_plan_is_labelled_when_consumed(self):
        server = _server()
        repo = MagicMock()

        with patch("mcp_server.LLMClient", return_value=_unavailable_llm()), patch(
            "mcp_server._agent_decision_repo", return_value=repo
        ), _hypotheses_patch():
            init = server.handle_agent_init(
                {
                    "target": "https://example.com",
                    "phase": "scan",
                    "pipeline": [{"tool": "nuclei"}, {"tool": "nmap"}],
                    "engagementId": ENGAGEMENT,
                }
            )
            step = server.handle_agent_next({"session_id": init["session_id"]})

        assert init["plan"] == ["nuclei", "nmap"]
        assert step["reasoning"] == "Deterministic plan step"

        call = repo.log_decision.call_args
        assert call.kwargs["tool_selected"] == "nuclei"
        assert call.kwargs["was_fallback"] is True
