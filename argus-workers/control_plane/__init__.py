"""Fact-and-intent control plane (bootstrap / reason / explore).

Strict worker result contracts, deterministic worker selection, the single
dispatcher and its PostgreSQL protocol state. Workers only return JSON; only
the dispatcher writes durable graph state.
"""

from control_plane.contracts import (
    DEFAULT_MAX_INTENTS,
    SCHEMA_VERSION,
    BootstrapConcludeResult,
    BootstrapExecuteResult,
    ExploreResult,
    ProtocolError,
    ReasonDecision,
    ReasonIntent,
    ResultRejected,
    parse_bootstrap_conclude,
    parse_bootstrap_execute,
    parse_explore_result,
    parse_reason_result,
    parse_worker_result,
)
from control_plane.dispatcher import ControlPlaneDispatcher, WorkerRunner
from control_plane.scheduler import WorkerView, choose_worker, global_capacity_available
from control_plane.store import (
    LateResult,
    LeaseLost,
    NotLeader,
    PostgresControlPlaneStore,
)

__all__ = [
    "DEFAULT_MAX_INTENTS",
    "SCHEMA_VERSION",
    "BootstrapConcludeResult",
    "BootstrapExecuteResult",
    "ControlPlaneDispatcher",
    "ExploreResult",
    "LateResult",
    "LeaseLost",
    "NotLeader",
    "PostgresControlPlaneStore",
    "ProtocolError",
    "ReasonDecision",
    "ReasonIntent",
    "ResultRejected",
    "WorkerView",
    "WorkerRunner",
    "choose_worker",
    "global_capacity_available",
    "parse_bootstrap_conclude",
    "parse_bootstrap_execute",
    "parse_explore_result",
    "parse_reason_result",
    "parse_worker_result",
]
