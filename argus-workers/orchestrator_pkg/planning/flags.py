"""
V2 orchestration feature flags and shadow mode (A5).

``ARGUS_ORCHESTRATION_V2``, ``ARGUS_GRAPH_EXPLORATION``,
``ARGUS_HIERARCHICAL_DELEGATION`` and ``ARGUS_FACT_INTENT_PROTOCOL`` each accept
``off``, ``shadow`` or ``on``.

**Defaults.** A deployment is expected to run the planner loop, so the shipped
deployment configuration (``docker-compose.yml``, ``.env.example``,
``start-argus.sh``) sets ``ARGUS_ORCHESTRATION_V2=on`` and
``ARGUS_GRAPH_EXPLORATION=on``. The unset fallback in this module is ``off``
on purpose: it is the per-process rollback switch, so a process started
without the deployment config (a library import, a test, a one-off worker) can
never mutate a live graph by accident. An unset flag therefore means "this
process was not configured to run the loop", not "the loop is unshipped".

``shadow`` may read the graph and record planning turns and proposals, but it
must not persist graph facts or dispatch new work; use it to compare the loop
against the deterministic coverage scheduler before switching ``on``.
``off`` is the rollback: the production planner drain task does nothing and the
legacy workflow path keeps running.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

MODES = ("off", "shadow", "on")

FLAG_ENV_NAMES = {
    "orchestration": "ARGUS_ORCHESTRATION_V2",
    "graph_exploration": "ARGUS_GRAPH_EXPLORATION",
    "hierarchical_delegation": "ARGUS_HIERARCHICAL_DELEGATION",
    "fact_intent_protocol": "ARGUS_FACT_INTENT_PROTOCOL",
}


def parse_mode(value: str | None, *, name: str = "flag") -> str:
    """Parse one flag value, rejecting typos instead of silently disabling."""
    if value is None or value == "":
        return "off"
    mode = value.strip().lower()
    if mode not in MODES:
        raise ValueError(
            f"{name} must be one of {', '.join(MODES)}; got {value!r}"
        )
    return mode


def flag_mode(flag: str) -> str:
    """Return the current mode for a named flag (default ``off``)."""
    env_name = FLAG_ENV_NAMES.get(flag)
    if env_name is None:
        raise KeyError(f"unknown orchestration flag: {flag}")
    return parse_mode(os.getenv(env_name), name=env_name)


def graph_exploration_mode() -> str:
    return flag_mode("graph_exploration")


def orchestration_mode() -> str:
    return flag_mode("orchestration")


def hierarchical_delegation_mode() -> str:
    """The hierarchical delegation switch (``off`` | ``shadow`` | ``on``)."""
    return flag_mode("hierarchical_delegation")


def effective_mode() -> str:
    """
    Resolve the mode the production drain actually runs in.

    ``ARGUS_ORCHESTRATION_V2`` is the master switch: ``off`` rolls back and
    ``shadow`` keeps the loop non-mutating. Only when it is ``on`` does
    ``ARGUS_GRAPH_EXPLORATION`` decide whether the loop runs live or shadow.
    """
    orchestration = orchestration_mode()
    if orchestration != "on":
        return orchestration
    return graph_exploration_mode()


def planner_loop_enabled() -> bool:
    """The production planner loop only runs when the effective mode is not off."""
    return effective_mode() != "off"


def mode_report() -> dict[str, Any]:
    """
    Describe the resolved modes for logs, health endpoints and support.

    Returns the raw flag values next to the resolved ``effective_mode`` and
    whether the loop will do work, so "the drain runs but does nothing" is
    explainable without reading this module.
    """
    orchestration = orchestration_mode()
    graph_exploration = graph_exploration_mode()
    effective = effective_mode()
    return {
        "orchestration": orchestration,
        "graph_exploration": graph_exploration,
        "effective": effective,
        "loop_enabled": effective != "off",
        "dispatch": effective == "on",
        "env": dict(FLAG_ENV_NAMES),
    }


def legacy_rollback_enabled() -> bool:
    """The one-switch rollback: V2 off means the legacy workflow path runs."""
    return effective_mode() == "off"


def shadow_plan(
    engagement_id: str,
    *,
    dispatcher: Any | None = None,
    planner: Any | None = None,
) -> dict[str, Any]:
    """
    Build a shadow planning proposal without persisting or dispatching anything.

    Returns the planner's proposals next to the gap keys the deterministic
    coverage scheduler would use, so a shadow comparison can be reviewed. No
    planner turn row, intent node, outbox row or recon dispatch is written.
    """
    from database import graph_worker_rpc
    from orchestrator_pkg.planning.exploration_planner import ExplorationPlanner

    planner = planner or ExplorationPlanner()
    if dispatcher is None:
        overview = graph_worker_rpc.planner_snapshot(engagement_id)
        deterministic = graph_worker_rpc.coverage_gap_keys(engagement_id)
    else:
        overview = dispatcher.planner_overview(engagement_id)
        deterministic = sorted(
            {
                str((todo.get("payload") or {}).get("coverage_gap_key"))
                for todo in dispatcher.find_todos_for_engagement(engagement_id)
                if (todo.get("payload") or {}).get("coverage_gap_key")
            }
        )
    proposals = planner.plan(overview)
    proposed_targets = sorted(
        {
            asset_id
            for proposal in proposals
            for asset_id in proposal.target_asset_ids
        }
    )
    return {
        "engagement_id": engagement_id,
        "mode": "shadow",
        "proposals": proposals,
        "proposed_targets": proposed_targets,
        "deterministic_gap_keys": deterministic,
        "would_create_intents": len(proposals),
        "wrote": False,
    }
