"""
Dispatcher-backed worker RPC facade (C-18/A4).

Workers and the MCP server must not import the graph write surface directly.
This module is the one allow-listed seam: it constructs ``DispatcherGraph`` and
calls its dispatcher-owned methods, so a worker can claim/heartbeat/complete one
intent, record idempotent action results and reuse traces without ever touching
the repository or committing graph state itself.
"""

from __future__ import annotations

from typing import Any

from database.dispatcher_graph import DispatcherGraph
from database.graph_repository import ExplorationGraphRepository


def _dispatcher() -> DispatcherGraph:
    return DispatcherGraph(ExplorationGraphRepository())


def claim_intent(
    engagement_id: str,
    worker_id: str,
    *,
    intent_node_id: str | None = None,
    lease_seconds: int = 90,
) -> dict[str, Any] | None:
    return _dispatcher().claim_intent_node(
        engagement_id,
        worker_id,
        intent_node_id=intent_node_id,
        lease_seconds=lease_seconds,
    )


def heartbeat_intent(
    engagement_id: str,
    intent_node_id: str,
    *,
    claim_token: str,
    lease_seconds: int = 90,
) -> dict[str, Any]:
    return _dispatcher().heartbeat_intent_node(
        engagement_id,
        intent_node_id,
        claim_token=claim_token,
        lease_seconds=lease_seconds,
    )


def complete_intent(
    engagement_id: str,
    intent_node_id: str,
    *,
    claim_token: str,
    fact_description: str,
) -> dict[str, Any]:
    return _dispatcher().complete_intent_node(
        engagement_id,
        intent_node_id,
        claim_token=claim_token,
        fact_description=fact_description,
    )


def worker_intent_package(
    engagement_id: str, intent_node_id: str, *, trace_limit: int = 5
) -> dict[str, Any]:
    return _dispatcher().worker_intent_package(
        engagement_id, intent_node_id, trace_limit=trace_limit
    )


def report_trace(
    engagement_id: str,
    summary: str,
    *,
    intent_node_id: str | None = None,
    worker_id: str | None = None,
    tool: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatcher().record_trace(
        engagement_id,
        summary,
        intent_node_id=intent_node_id,
        worker_id=worker_id,
        tool=tool,
        payload=payload,
    )


def search_traces(
    engagement_id: str,
    *,
    query: str | None = None,
    intent_node_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return _dispatcher().search_traces(
        engagement_id,
        query=query,
        intent_node_id=intent_node_id,
        limit=limit,
    )


def record_action(
    engagement_id: str,
    action_id: str,
    *,
    intent_node_id: str | None = None,
    worker_id: str | None = None,
    tool: str | None = None,
    canonical_arguments: dict[str, Any] | None = None,
    outcome: str = "completed",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatcher().record_action(
        engagement_id,
        action_id,
        intent_node_id=intent_node_id,
        worker_id=worker_id,
        tool=tool,
        canonical_arguments=canonical_arguments,
        outcome=outcome,
        result=result,
    )


def planner_snapshot(engagement_id: str) -> dict[str, Any]:
    return _dispatcher().planner_overview(engagement_id)


def coverage_gap_keys(engagement_id: str) -> list[str]:
    return sorted(
        {
            str((todo.get("payload") or {}).get("coverage_gap_key"))
            for todo in _dispatcher().find_todos_for_engagement(engagement_id)
            if (todo.get("payload") or {}).get("coverage_gap_key")
        }
    )
