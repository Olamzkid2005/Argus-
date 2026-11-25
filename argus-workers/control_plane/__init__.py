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
from control_plane.integrated import (
    IntegratedWorkerRunner,
    build_integrated_runner,
    integrated_runner_from_env,
)
from control_plane.scheduler import WorkerView, choose_worker, global_capacity_available
from control_plane.store import (
    LateResult,
    LeaseLost,
    NotLeader,
    PostgresControlPlaneStore,
)
from control_plane.task_service import (
    METHODS as TASK_METHODS,
)
from control_plane.task_service import (
    TaskRequest,
    dispatch_task_request,
    get_task_executor,
    parse_task_request,
    set_task_executor,
)
from control_plane.worker_bridge import MCPTaskBridge, worker_runner_from_env

__all__ = [
    "DEFAULT_MAX_INTENTS",
    "MCPTaskBridge",
    "TASK_METHODS",
    "TaskRequest",
    "SCHEMA_VERSION",
    "BootstrapConcludeResult",
    "BootstrapExecuteResult",
    "ControlPlaneDispatcher",
    "ExploreResult",
    "IntegratedWorkerRunner",
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
    "build_integrated_runner",
    "choose_worker",
    "dispatch_task_request",
    "get_task_executor",
    "global_capacity_available",
    "integrated_runner_from_env",
    "parse_task_request",
    "parse_bootstrap_conclude",
    "parse_bootstrap_execute",
    "parse_explore_result",
    "parse_reason_result",
    "parse_worker_result",
    "set_task_executor",
    "worker_runner_from_env",
]
