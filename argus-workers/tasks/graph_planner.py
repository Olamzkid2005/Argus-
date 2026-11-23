"""
Coverage-gap recon planner (A2).

``schedule_coverage_gaps`` writes approved-but-undiscovered targets and untested
asset classes onto the planner frontier as open todos. This module is the other
half of that loop: it claims the next gap through the dispatcher-owned
frontier/todo selection, derives recon targets from the gap, and dispatches the
existing recon task with the gap's todo id. When that recon pass finishes it
ingests its outcomes and calls :func:`complete_coverage_gap`, which closes the
todo, clears the frontier row and records coverage of the produced assets, so
recomputed coverage no longer reports the gap.

Dispatch goes through ``dispatch_task.dispatch_task`` (Celery ``send_task``).
The ``dispatch`` parameter exists because the recon run itself is outside this
process; production callers use the default.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from database.dispatcher_graph import DispatcherGraph
from database.graph_repository import ExplorationGraphRepository

# Worker processes and CI have the full task stack; the planner's selection,
# dispatch and completion helpers stay importable without it (e.g. a minimal
# Postgres-only test environment), so the Celery task is registered when the
# app is available.
try:
    from celery_app import app
except ImportError:  # pragma: no cover - exercised only without worker deps
    app = None

logger = logging.getLogger(__name__)

RECON_TASK_NAME = "tasks.recon.expand_recon"
_MAX_TARGETS = 25


def _default_dispatch(task_name: str, args: list) -> dict:
    """Send recon work through the real Celery task dispatcher."""
    from dispatch_task import dispatch_task

    return dispatch_task(task_name, args)


def _scope_entry_target(entry_kind: str | None, entry_value: str | None) -> list[str]:
    """Turn an approved scope entry into a recon target."""
    value = (entry_value or "").strip()
    if not value:
        return []
    if entry_kind == "domain":
        if "://" in value:
            return [value]
        # A wildcard approval covers its apex for a first recon pass.
        host = value[2:] if value.startswith("*.") else value
        return [f"https://{host}"]
    # CIDR ranges are handed to recon unchanged; the tool/runner expands them.
    return [value]


def _class_targets(
    dispatcher: DispatcherGraph, engagement_id: str, asset_type: str
) -> list[str]:
    """Target the in-scope assets of an untested class that recon has not covered."""
    report = dispatcher.coverage_report(engagement_id)
    targets: list[str] = []
    for asset in report["assets"]:
        if asset["asset_type"] != asset_type or not asset["untested"]:
            continue
        value = asset.get("display_value") or asset["canonical_key"]
        if value and value not in targets:
            targets.append(value)
        if len(targets) >= _MAX_TARGETS:
            break
    return targets


def recon_targets_for_todo(
    dispatcher: DispatcherGraph, engagement_id: str, todo: dict
) -> list[str]:
    """Derive recon targets from a claimed coverage-gap todo."""
    payload = todo.get("payload") or {}
    gap_type = payload.get("gap_type")
    if gap_type == "approved_but_undiscovered":
        return _scope_entry_target(
            payload.get("entry_kind"), payload.get("entry_value")
        )
    if gap_type == "untested_asset_class":
        asset_type = payload.get("asset_type")
        if not asset_type:
            return []
        return _class_targets(dispatcher, engagement_id, asset_type)
    return []


def dispatch_next_coverage_gap(
    engagement_id: str,
    *,
    worker_id: str,
    dispatcher: DispatcherGraph | None = None,
    dispatch: Callable[[str, list], dict] | None = None,
    budget: dict | None = None,
    trace_id: str | None = None,
    lease_seconds: int = 300,
    gap_key: str | None = None,
) -> dict[str, Any]:
    """
    Claim one scheduled coverage gap and dispatch it as recon work.

    Returns ``{"status": "dispatched", ...}`` with the todo id, gap key, targets
    and dispatch result, ``{"status": "idle"}`` when the engagement has no
    claimable gap (including when the work belongs to another engagement), or
    ``{"status": "skipped"}`` when the gap no longer has targets.
    """
    if not engagement_id or not worker_id:
        return {"status": "error", "reason": "engagement_id and worker_id required"}

    dispatcher = dispatcher or DispatcherGraph(ExplorationGraphRepository())
    todo = dispatcher.claim_recon_todo(
        engagement_id,
        owner=worker_id,
        lease_seconds=lease_seconds,
        gap_key=gap_key,
    )
    if todo is None:
        return {"status": "idle", "engagement_id": engagement_id}

    payload = todo.get("payload") or {}
    targets = recon_targets_for_todo(dispatcher, engagement_id, todo)
    if not targets:
        dispatcher.release_recon_todo(
            engagement_id, todo["id"], reason="no_recon_targets"
        )
        return {
            "status": "skipped",
            "reason": "no_recon_targets",
            "engagement_id": engagement_id,
            "todo_id": todo["id"],
            "gap_key": payload.get("coverage_gap_key"),
        }

    send = dispatch or _default_dispatch
    try:
        result = send(
            RECON_TASK_NAME,
            [
                engagement_id,
                targets,
                dict(budget or {}),
                trace_id,
                todo["id"],
            ],
        )
    except Exception as exc:  # noqa: BLE001 - dispatch failure must release the claim
        logger.warning(
            "Dispatching coverage gap %s for engagement %s failed: %s",
            payload.get("coverage_gap_key"),
            engagement_id,
            exc,
        )
        dispatcher.release_recon_todo(
            engagement_id, todo["id"], reason=f"dispatch_failed: {exc}"
        )
        return {
            "status": "dispatch_failed",
            "engagement_id": engagement_id,
            "todo_id": todo["id"],
            "gap_key": payload.get("coverage_gap_key"),
            "error": str(exc),
        }

    logger.info(
        "Dispatched coverage gap %s for engagement %s as %s (todo=%s, targets=%s)",
        payload.get("coverage_gap_key"),
        engagement_id,
        RECON_TASK_NAME,
        todo["id"],
        targets,
    )
    return {
        "status": "dispatched",
        "engagement_id": engagement_id,
        "todo_id": todo["id"],
        "gap_key": payload.get("coverage_gap_key"),
        "gap_type": payload.get("gap_type"),
        "targets": targets,
        "task_id": (result or {}).get("task_id"),
    }


def complete_coverage_gap(
    engagement_id: str,
    todo_id: str,
    *,
    asset_ids: list[str] | None = None,
    dispatcher: DispatcherGraph | None = None,
) -> dict[str, Any]:
    """
    Close a dispatched coverage gap after its recon results were ingested.

    This is called by the recon task itself, so the completion always reuses the
    same dispatcher-owned path that claimed the todo.
    """
    dispatcher = dispatcher or DispatcherGraph(ExplorationGraphRepository())
    return dispatcher.complete_recon_todo(
        engagement_id, todo_id, asset_ids=asset_ids
    )


def _dispatch_coverage_gap(
    self,
    engagement_id: str,
    budget: dict | None = None,
    trace_id: str | None = None,
    worker_id: str | None = None,
):
    """Dispatch one scheduled coverage gap as recon work."""
    request_id = getattr(getattr(self, "request", None), "id", None)
    resolved_worker = worker_id or f"planner-{request_id or 'local'}"
    return dispatch_next_coverage_gap(
        engagement_id,
        worker_id=resolved_worker,
        budget=budget,
        trace_id=trace_id,
    )


dispatch_coverage_gap = (
    app.task(bind=True, name="tasks.graph.dispatch_coverage_gap")(
        _dispatch_coverage_gap
    )
    if app is not None
    else _dispatch_coverage_gap
)
