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
from orchestrator_pkg.planning.exploration_planner import ExplorationPlanner

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


class PlannerHardFloorError(RuntimeError):
    """A planning turn left an unmet goal with no open/running intent (A-07)."""


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
    claim_token = todo.get("claim_token")
    if not targets:
        dispatcher.release_recon_todo(
            engagement_id,
            todo["id"],
            claim_token=claim_token,
            reason="no_recon_targets",
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
                claim_token,
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
            engagement_id,
            todo["id"],
            claim_token=claim_token,
            reason=f"dispatch_failed: {exc}",
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
        "claim_token": claim_token,
        "task_id": (result or {}).get("task_id"),
    }


def complete_coverage_gap(
    engagement_id: str,
    todo_id: str,
    *,
    claim_token: str | None = None,
    asset_ids: list[str] | None = None,
    dispatcher: DispatcherGraph | None = None,
) -> dict[str, Any]:
    """
    Close a dispatched coverage gap after its recon results were ingested.

    This is called by the recon task itself, so the completion always reuses the
    same dispatcher-owned path that claimed the todo, including its fencing token.
    """
    dispatcher = dispatcher or DispatcherGraph(ExplorationGraphRepository())
    return dispatcher.complete_recon_todo(
        engagement_id,
        todo_id,
        claim_token=claim_token,
        asset_ids=asset_ids,
    )


def run_planner_turn(
    engagement_id: str,
    *,
    dispatcher: DispatcherGraph | None = None,
    planner: ExplorationPlanner | None = None,
    trigger: str = "outbox",
    consume_events: bool = True,
    shadow: bool = False,
) -> dict[str, Any]:
    """
    Run one persisted planning turn.

    The turn consumes the engagement's current outbox burst as one batch, asks the
    planner for typed intent proposals, validates/persists them through the
    dispatcher, enforces the hard floor and records the turn's counts. Any failure
    marks the turn failed before re-raising, so a bad turn is visible rather than a
    silent no-op.
    """
    dispatcher = dispatcher or DispatcherGraph(ExplorationGraphRepository())
    planner = planner or ExplorationPlanner()
    turn = dispatcher.begin_planner_turn(engagement_id, trigger=trigger)
    try:
        consumed = (
            dispatcher.consume_planner_events(engagement_id, turn["id"])
            if consume_events
            else []
        )
        overview = dispatcher.planner_overview(engagement_id)
        proposals = planner.plan(overview)
        if shadow:
            # Shadow mode records what would have been proposed without creating
            # intents, dispatching work or tripping the live hard floor.
            applied = {
                "created": [],
                "suppressed": [],
                "proposals_received": len(proposals),
            }
        else:
            applied = dispatcher.apply_intent_proposals(engagement_id, proposals)

        after = dispatcher.planner_overview(engagement_id)
        unmet_goals = [
            goal for goal in after["goals"] if goal.get("state") != "concluded"
        ]
        if not shadow and unmet_goals and not after["open_intents"]:
            raise PlannerHardFloorError(
                "planner turn left unmet goal(s) "
                f"{sorted(str(goal['id']) for goal in unmet_goals)} with no open or "
                "running intent; the planner must propose applicable work or fail"
            )

        completed = dispatcher.complete_planner_turn(
            turn["id"],
            events_consumed=len(consumed),
            proposals_received=applied["proposals_received"],
            intents_created=len(applied["created"]),
            duplicates_suppressed=len(applied["suppressed"]),
        )
    except Exception as exc:
        dispatcher.fail_planner_turn(turn["id"], str(exc))
        raise

    return {
        "turn": completed,
        "events_consumed": len(consumed),
        "event_ids": [str(event["id"]) for event in consumed],
        "created": applied["created"],
        "suppressed": applied["suppressed"],
        "shadow": shadow,
    }


def run_planner_loop(
    engagement_id: str,
    *,
    max_turns: int = 10,
    dispatcher: DispatcherGraph | None = None,
    planner: ExplorationPlanner | None = None,
    shadow: bool = False,
) -> dict[str, Any]:
    """
    Consume queued outbox work in bounded, debounced planning turns.

    All events queued for the engagement at the start of a turn are coalesced into
    that one turn (the debounce is the batch boundary). The loop stops when no
    queued events remain or ``max_turns`` is reached, so a planner that keeps
    producing graph changes cannot spin forever; leftover rows stay queued for the
    next loop pass instead of being stranded.
    """
    if max_turns < 1:
        raise ValueError("max_turns must be at least 1")
    dispatcher = dispatcher or DispatcherGraph(ExplorationGraphRepository())
    planner = planner or ExplorationPlanner()

    turns = 0
    events_consumed = 0
    while turns < max_turns:
        if dispatcher.count_queued_outbox(engagement_id) == 0:
            return {
                "engagement_id": engagement_id,
                "turns": turns,
                "events_consumed": events_consumed,
                "stopped_reason": "idle",
            }
        result = run_planner_turn(
            engagement_id,
            dispatcher=dispatcher,
            planner=planner,
            shadow=shadow,
        )
        turns += 1
        events_consumed += result["events_consumed"]

    return {
        "engagement_id": engagement_id,
        "turns": turns,
        "events_consumed": events_consumed,
        "stopped_reason": "max_turns",
    }


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


def drain_planner_outbox(
    *,
    dispatcher: DispatcherGraph | None = None,
    planner: ExplorationPlanner | None = None,
    max_engagement_turns: int = 10,
    mode: str | None = None,
) -> dict[str, Any]:
    """
    Consume every engagement's queued outbox work in bounded planning turns.

    This is the production entry point the Celery beat task calls. It is the
    floor that guarantees committed graph changes are never stranded: even if an
    immediate wake dispatch is missed, the next drain consumes the queue.

    ``mode`` follows the V2 flags: ``off`` is the rollback switch and does
    nothing, ``shadow`` records turns and proposals but creates no intents and
    dispatches no work, and ``on`` runs the live loop.
    """
    from orchestrator_pkg.planning.flags import graph_exploration_mode, parse_mode

    resolved = parse_mode(mode, name="mode") if mode is not None else graph_exploration_mode()
    if resolved == "off":
        return {
            "mode": resolved,
            "engagements": 0,
            "turns": 0,
            "results": [],
            "skipped": True,
        }

    dispatcher = dispatcher or DispatcherGraph(ExplorationGraphRepository())
    planner = planner or ExplorationPlanner()

    results: list[dict[str, Any]] = []
    total_turns = 0
    for engagement_id in dispatcher.find_engagements_with_queued_outbox():
        try:
            loop = run_planner_loop(
                engagement_id,
                max_turns=max_engagement_turns,
                dispatcher=dispatcher,
                planner=planner,
                shadow=resolved == "shadow",
            )
        except PlannerHardFloorError as exc:
            logger.error(
                "Planner hard floor for engagement %s: %s", engagement_id, exc
            )
            results.append({"engagement_id": engagement_id, "error": str(exc)})
            continue
        total_turns += loop["turns"]
        results.append(
            {
                "engagement_id": engagement_id,
                "turns": loop["turns"],
                "events_consumed": loop["events_consumed"],
                "stopped_reason": loop["stopped_reason"],
            }
        )

    return {
        "mode": resolved,
        "engagements": len(results),
        "turns": total_turns,
        "results": results,
        "skipped": False,
    }


def _run_planner_loop_task(self, engagement_id: str, max_turns: int = 10):
    """Celery entry point: drain one engagement's queued outbox burst."""
    return run_planner_loop(engagement_id, max_turns=max_turns)


def _drain_planner_outbox_task(self, max_turns: int = 10):
    """Celery beat entry point: drain every engagement with queued wakes."""
    return drain_planner_outbox(max_engagement_turns=max_turns)


run_planner_loop_task = (
    app.task(
        bind=True,
        name="tasks.graph_planner.run_planner_loop",
        soft_time_limit=240,
        time_limit=300,
    )(_run_planner_loop_task)
    if app is not None
    else _run_planner_loop_task
)

drain_planner_outbox_task = (
    app.task(
        bind=True,
        name="tasks.graph_planner.drain_planner_outbox",
        soft_time_limit=240,
        time_limit=300,
    )(_drain_planner_outbox_task)
    if app is not None
    else _drain_planner_outbox_task
)
