"""Celery entry point for the fact-and-intent dispatcher tick.

The beat schedule runs :func:`run_control_plane_tick`: it finds active
engagements, acquires the per-engagement dispatcher lease and runs at most one
protocol step (bootstrap, reason or explore). The worker transport is the typed
stdio ``task_*`` MCP bridge (``ARGUS_TASK_WORKER_CMD``) when configured, else
the integrated in-process runner (``ARGUS_INTEGRATED_TASK_AGENTS``), whose
explore path runs the production tool executor by default — so the same
dispatcher that the conformance tests drive also runs in a normal Celery
worker.

``ARGUS_FACT_INTENT_PROTOCOL`` is the switch (``off`` default, ``shadow`` only lists
eligible engagements, ``on`` dispatches). With no worker transport configured
(``ARGUS_TASK_WORKER_CMD``) the tick reports ``unconfigured`` and dispatches
nothing instead of pretending work was queued.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from control_plane import (
    ControlPlaneDispatcher,
    NotLeader,
    PostgresControlPlaneStore,
    WorkerRunner,
)
from control_plane.integrated import integrated_runner_from_env
from control_plane.worker_bridge import worker_runner_from_env

try:
    from celery_app import app
except ImportError:  # pragma: no cover - minimal Postgres-only test environment
    app = None

logger = logging.getLogger(__name__)

DISPATCHED_OUTCOMES = frozenset({"bootstrap", "reason", "explore"})


def _worker_limit() -> int:
    try:
        return max(1, int(os.getenv("ARGUS_CONTROL_PLANE_WORKER_CONCURRENCY", "1")))
    except ValueError:
        logger.warning(
            "ARGUS_CONTROL_PLANE_WORKER_CONCURRENCY is not an integer; using 1"
        )
        return 1


def _register_runner(store: PostgresControlPlaneStore, runner: WorkerRunner) -> None:
    """Publish the configured transport as a schedulable worker."""
    worker_id = getattr(runner, "worker_id", None)
    task_types = getattr(runner, "task_types", None)
    if not worker_id or not task_types:
        return
    store.register_worker(
        str(worker_id),
        sorted(str(item) for item in task_types),
        max_running=_worker_limit(),
    )


def run_control_plane_tick(
    *,
    store: PostgresControlPlaneStore | None = None,
    runner: WorkerRunner | None = None,
    mode: str | None = None,
    engagement_ids: list[str] | None = None,
    max_engagements: int = 5,
    owner: str | None = None,
) -> dict[str, Any]:
    """Advance every selected engagement by at most one protocol step."""
    from orchestrator_pkg.planning.flags import flag_mode, parse_mode

    resolved = (
        parse_mode(mode, name="mode") if mode is not None else flag_mode("fact_intent_protocol")
    )
    if max_engagements < 1:
        raise ValueError("max_engagements must be positive")

    store = store or PostgresControlPlaneStore()
    if engagement_ids is None:
        engagements = store.list_active_engagements(limit=max_engagements)
    else:
        engagements = [str(item) for item in engagement_ids][:max_engagements]

    if resolved != "on":
        if resolved == "off":
            logger.warning(
                "Control-plane tick is disabled (ARGUS_FACT_INTENT_PROTOCOL=%r); "
                "set it to 'on' to dispatch bootstrap/reason/explore work.",
                os.getenv("ARGUS_FACT_INTENT_PROTOCOL"),
            )
        return {
            "mode": resolved,
            "engagements": engagements,
            "dispatched": 0,
            "results": [],
            "skipped": True,
        }

    runner = runner or worker_runner_from_env() or integrated_runner_from_env()
    if runner is None:
        logger.warning(
            "Control-plane tick has no worker transport: set ARGUS_TASK_WORKER_CMD "
            "(for example 'python mcp_server.py') or "
            "ARGUS_INTEGRATED_TASK_AGENTS=module:factory to dispatch work."
        )
        return {
            "mode": resolved,
            "engagements": engagements,
            "dispatched": 0,
            "results": [],
            "status": "unconfigured",
        }

    _register_runner(store, runner)
    instance = owner or f"control-plane-{os.getpid()}"

    results: list[dict[str, Any]] = []
    dispatched = 0
    for engagement_id in engagements:
        dispatcher = ControlPlaneDispatcher(store, runner, owner=instance)
        outcome: str | None
        error: str | None = None
        try:
            dispatcher.acquire_leadership(engagement_id)
            outcome = dispatcher.tick(engagement_id)
        except NotLeader:
            outcome = "not_leader"
        except Exception as exc:  # one broken engagement must not stop the tick
            logger.exception("control-plane tick failed for %s", engagement_id)
            outcome = "error"
            error = str(exc)
        finally:
            dispatcher.release_leadership(engagement_id)
        if outcome in DISPATCHED_OUTCOMES:
            dispatched += 1
        entry: dict[str, Any] = {"engagement_id": engagement_id, "outcome": outcome}
        if error is not None:
            entry["error"] = error
        results.append(entry)

    return {
        "mode": resolved,
        "engagements": engagements,
        "dispatched": dispatched,
        "results": results,
    }


def _tick_task(self, **kwargs: Any) -> dict[str, Any]:
    """Celery beat entry point: one bounded dispatcher pass."""
    return run_control_plane_tick(**kwargs)


control_plane_tick = (
    app.task(
        bind=True,
        name="tasks.control_plane.tick",
        soft_time_limit=240,
        time_limit=300,
    )(_tick_task)
    if app is not None
    else _tick_task
)
