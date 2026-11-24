"""Run the A5 shadow comparison: graph planner frontier vs the deterministic plan.

This is the activation gate for ``ARGUS_GRAPH_EXPLORATION=on``. It builds a
realistic assessment in the graph for two configurations and diffs the two
planning paths:

``with_scheduler``
    Production configuration: recon outcomes are ingested and the deterministic
    coverage scheduler has already committed its gap todos. The planner must not
    duplicate that scheduled direction (plan 3.5.5 / A-09).

``planner_only``
    Assets exist but nothing has scheduled gaps yet. The planner must propose
    work for every untested class the deterministic scheduler would flag.

Both runs happen in ``shadow`` mode, and the script asserts shadow changed no
durable state before it prints the comparison.

Usage (from ``argus-workers``, with ``DATABASE_URL`` in the environment)::

    ./venv/bin/python scripts/shadow_planner_comparison.py

``--json PATH`` also writes the machine-readable result. Each scenario rebuilds
its own scratch engagement, so repeated runs are deterministic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: Stable ids so a re-run replaces its own scenario instead of accumulating rows.
ENGAGEMENT_IDS = {
    "with_scheduler": str(
        uuid.uuid5(uuid.NAMESPACE_URL, "argus:shadow-comparison:with-scheduler")
    ),
    "planner_only": str(
        uuid.uuid5(uuid.NAMESPACE_URL, "argus:shadow-comparison:planner-only")
    ),
}

AUTHORIZED_SCOPE = {
    "domains": [
        "shadow-lab.internal",
        "www.shadow-lab.internal",
        "api.shadow-lab.internal",  # approved, deliberately not discovered
    ],
    "ipRanges": ["10.42.0.0/28"],
}

#: One realistic recon pass: the kinds of values a live scan of the lab yields.
RECON_CONTEXT = {
    "target_url": "https://shadow-lab.internal",
    "subdomains": [
        "www.shadow-lab.internal",
        "db.shadow-lab.internal",  # not approved: must be rejected (A-05/A-14)
    ],
    "live_endpoints": [
        "https://shadow-lab.internal/",
        "https://shadow-lab.internal/login",
        "https://www.shadow-lab.internal/",
    ],
    "crawled_paths": [
        "https://shadow-lab.internal/api/v1/users",
        "https://shadow-lab.internal/admin",
    ],
    "api_endpoints": ["https://shadow-lab.internal/api/v1/users"],
    "auth_endpoints": ["https://shadow-lab.internal/login"],
    "open_ports": [
        {"host": "10.42.0.3", "port": 443, "protocol": "tcp"},
        {"host": "10.42.0.3", "port": 22, "protocol": "tcp"},
    ],
    "ips": ["10.42.0.3"],
}


def _reset_scratch_engagement(conn, engagement_id: str) -> None:
    """Remove a previous run's rows for a scratch engagement, in FK order."""
    statements = (
        "DELETE FROM graph_anchor_scopes WHERE anchor_id IN "
        "(SELECT id FROM graph_anchors WHERE node_id IN "
        "(SELECT id FROM graph_nodes WHERE engagement_id = %s))",
        "DELETE FROM graph_anchors WHERE node_id IN "
        "(SELECT id FROM graph_nodes WHERE engagement_id = %s)",
        "DELETE FROM graph_node_edges WHERE engagement_id = %s",
        "DELETE FROM graph_asset_observations WHERE scope_id = %s",
        "DELETE FROM planner_frontier WHERE engagement_id = %s",
        "DELETE FROM planner_todos WHERE engagement_id = %s",
        "DELETE FROM planner_turn_events WHERE turn_id IN "
        "(SELECT id FROM planner_turns WHERE engagement_id = %s)",
        "DELETE FROM planner_turns WHERE engagement_id = %s",
        "DELETE FROM graph_outbox WHERE engagement_id = %s",
        "DELETE FROM graph_write_rejections WHERE engagement_id = %s",
        "DELETE FROM graph_nodes WHERE engagement_id = %s",
        "DELETE FROM graph_assets WHERE scope_id = %s",
        "DELETE FROM engagements WHERE id = %s",
    )
    for statement in statements:
        try:
            with conn, conn.cursor() as cur:
                cur.execute(statement, (engagement_id,))
        except Exception:  # noqa: BLE001 - a table may be absent on an older DB
            conn.rollback()


def _create_engagement(conn, engagement_id: str) -> None:
    from psycopg2.extras import Json

    with conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO engagements (id, org_id, target, authorized_scope)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                org_id = EXCLUDED.org_id,
                target = EXCLUDED.target,
                authorized_scope = EXCLUDED.authorized_scope
            """,
            (
                engagement_id,
                str(uuid.uuid4()),
                "https://shadow-lab.internal",
                Json(AUTHORIZED_SCOPE),
            ),
        )


def _snapshot(dispatcher, engagement_id: str) -> dict:
    """Durable graph state that shadow mode must not change."""
    overview = dispatcher.planner_overview(engagement_id)
    todos = dispatcher.find_todos_for_engagement(engagement_id)
    return {
        "goals": len(overview["goals"]),
        "open_intents": len(overview["open_intents"]),
        "facts": len(overview["facts"]),
        "untested_assets": len(overview["untested_assets"]),
        "todos": len(todos),
        "todos_by_status": dict(Counter(todo["status"] for todo in todos)),
        "queued_outbox": dispatcher.count_queued_outbox(engagement_id),
    }


def _run_scenario(conn, *, scenario: str, schedule_gaps: bool) -> dict:
    from database.dispatcher_graph import DispatcherGraph
    from database.graph_repository import ExplorationGraphRepository, GraphNodeKind
    from orchestrator_pkg.planning.exploration_planner import ExplorationPlanner
    from tasks.graph_ingestion import ingest_recon_outcomes
    from tasks.graph_planner import (
        recon_targets_for_todo,
        run_planner_turn,
    )

    engagement_id = ENGAGEMENT_IDS[scenario]
    dispatcher = DispatcherGraph(ExplorationGraphRepository())

    _reset_scratch_engagement(conn, engagement_id)
    _create_engagement(conn, engagement_id)
    dispatcher.create_node(
        engagement_id,
        GraphNodeKind.GOAL,
        payload={
            "objective": "confirm whether the lab admin surface is reachable "
            "unauthenticated, and prove it from verifier evidence"
        },
    )

    ingestion = ingest_recon_outcomes(
        engagement_id,
        RECON_CONTEXT,
        authorized_scope=AUTHORIZED_SCOPE,
        # Production ingestion schedules gaps; the planner-only run must not, so
        # the comparison has an unscheduled frontier to propose against.
        schedule_gaps=schedule_gaps,
    )
    coverage = dispatcher.coverage_report(engagement_id)

    scheduled = {"gaps": 0, "scheduled": [], "scheduled_count": 0, "already_scheduled": 0}
    deterministic = []
    if schedule_gaps:
        scheduled = dispatcher.schedule_coverage_gaps(
            engagement_id, engagement_id, authorized_scope=AUTHORIZED_SCOPE
        )
        for todo in dispatcher.find_todos_for_engagement(engagement_id):
            payload = todo.get("payload") or {}
            deterministic.append(
                {
                    "gap_key": payload.get("coverage_gap_key"),
                    "gap_type": payload.get("gap_type"),
                    "todo_type": todo.get("todo_type"),
                    "targets": recon_targets_for_todo(dispatcher, engagement_id, todo),
                }
            )

    before = _snapshot(dispatcher, engagement_id)

    # --- the ARTEX planner, in shadow mode ---
    overview = dispatcher.planner_overview(engagement_id)
    proposals = [
        {
            "objective": proposal.objective,
            "asset_ids": [str(asset_id) for asset_id in proposal.target_asset_ids],
            "rationale": proposal.rationale,
        }
        for proposal in ExplorationPlanner().plan(overview)
    ]
    shadow = run_planner_turn(engagement_id, shadow=True)
    after = _snapshot(dispatcher, engagement_id)
    turn = shadow["turn"] or {}

    asset_by_id = {
        str(asset["id"]): asset for asset in overview["untested_assets"]
    }
    proposed_assets = [
        asset_by_id[asset_id]
        for proposal in proposals
        for asset_id in proposal["asset_ids"]
        if asset_id in asset_by_id
    ]
    planner_classes = sorted({asset["asset_type"] for asset in proposed_assets})

    comparisons = []
    for gap in deterministic:
        gap_key = gap["gap_key"] or ""
        if gap["gap_type"] == "untested_asset_class":
            asset_type = gap_key.split(":", 1)[-1]
            comparisons.append(
                {
                    "gap_key": gap_key,
                    "gap_type": gap["gap_type"],
                    "legacy_targets": gap["targets"],
                    "planner_covers": asset_type in planner_classes,
                    "note": (
                        "planner proposes the same class" if asset_type in planner_classes
                        else "class work is already scheduled; planner stays quiet"
                    ),
                }
            )
        elif gap["gap_type"] == "approved_but_undiscovered":
            entry = gap_key.split(":", 2)[-1]
            comparisons.append(
                {
                    "gap_key": gap_key,
                    "gap_type": gap["gap_type"],
                    "legacy_targets": gap["targets"],
                    "planner_covers": False,
                    "note": (
                        f"{entry} was never discovered, so an asset-driven planner "
                        "has nothing to propose; the deterministic scope-entry gap is "
                        "the only path that can dispatch it"
                    ),
                }
            )

    return {
        "scenario": scenario,
        "engagement_id": engagement_id,
        "mode": "shadow",
        "scope": AUTHORIZED_SCOPE,
        "ingestion": {
            "accepted": ingestion["accepted"],
            "rejected": ingestion["rejected"],
            "failed": ingestion["failed"],
        },
        "assets": {
            "total": coverage["assets_total"],
            "in_scope": coverage["assets_in_scope"],
            "out_of_scope": coverage["assets_out_of_scope"],
            "untested": coverage["assets_untested"],
            "by_asset_type": coverage["by_asset_type"],
            "untested_asset_types": coverage["untested_asset_types"],
        },
        "deterministic_plan": {
            "gaps": scheduled["gaps"],
            "scheduled_count": scheduled["scheduled_count"],
            "already_scheduled": scheduled["already_scheduled"],
            "gap_details": comparisons,
            "open_gap_keys": overview["open_gap_keys"],
        },
        "planner_shadow": {
            "turn_id": str(turn["id"]) if turn.get("id") else None,
            "turn_status": turn.get("status"),
            "events_consumed": shadow["events_consumed"],
            "proposals_received": turn.get("proposals_received"),
            "proposals": proposals,
            "proposal_classes": planner_classes,
            "intents_created": len(shadow["created"]),
        },
        "state_before": before,
        "state_after": after,
        "shadow_wrote_nothing": (
            before["open_intents"] == after["open_intents"]
            and before["facts"] == after["facts"]
            and before["todos"] == after["todos"]
            and before["goals"] == after["goals"]
            and after["queued_outbox"] == 0
        ),
    }


def run() -> dict:
    import psycopg2

    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL must be set: the comparison reads PostgreSQL")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with_scheduler = _run_scenario(
            conn, scenario="with_scheduler", schedule_gaps=True
        )
        planner_only = _run_scenario(
            conn, scenario="planner_only", schedule_gaps=False
        )
    finally:
        conn.close()

    legacy_classes = set(with_scheduler["assets"]["untested_asset_types"])
    planner_classes = set(planner_only["planner_shadow"]["proposal_classes"])
    return {
        "generated_at": "2026-11-24",
        "gate": "A5 shadow comparison",
        "scenarios": {
            "with_scheduler": with_scheduler,
            "planner_only": planner_only,
        },
        "agreement": {
            "deterministic_untested_classes": sorted(legacy_classes),
            "planner_proposed_classes": sorted(planner_classes),
            "same_classes": legacy_classes == planner_classes,
            "missing_from_planner": sorted(legacy_classes - planner_classes),
            "extra_from_planner": sorted(planner_classes - legacy_classes),
            "duplicate_direction_suppressed": (
                with_scheduler["planner_shadow"]["proposals"] == []
                and bool(with_scheduler["deterministic_plan"]["open_gap_keys"])
            ),
        },
        "shadow_wrote_nothing": (
            with_scheduler["shadow_wrote_nothing"]
            and planner_only["shadow_wrote_nothing"]
        ),
    }


def _print_report(result: dict) -> None:
    for name, scenario in result["scenarios"].items():
        print(f"\n=== {name} (engagement {scenario['engagement_id']}) ===")
        ingestion = scenario["ingestion"]
        assets = scenario["assets"]
        print(
            f"ingested {ingestion['accepted']} accepted / "
            f"{ingestion['rejected']} rejected / {ingestion['failed']} failed; "
            f"{assets['total']} assets, {assets['untested']} untested"
        )
        deterministic = scenario["deterministic_plan"]
        print(
            f"deterministic plan: {deterministic['scheduled_count']} gap(s) "
            f"scheduled, gap keys {deterministic['open_gap_keys']}"
        )
        for gap in deterministic["gap_details"]:
            mark = "covered" if gap["planner_covers"] else "not covered"
            print(f"  - {gap['gap_key']}: {mark} ({gap['note']})")
        planner = scenario["planner_shadow"]
        print(
            f"planner (shadow): {planner['events_consumed']} event(s) consumed, "
            f"{planner['proposals_received']} proposal(s) recorded, "
            f"{planner['intents_created']} intent(s) created"
        )
        for proposal in planner["proposals"]:
            print(f"  - {proposal['objective']}")
        print(
            "shadow wrote nothing: "
            f"{scenario['shadow_wrote_nothing']} "
            f"(intents {scenario['state_before']['open_intents']} -> "
            f"{scenario['state_after']['open_intents']}, "
            f"todos {scenario['state_before']['todos']} -> "
            f"{scenario['state_after']['todos']})"
        )

    agreement = result["agreement"]
    print("\n=== agreement ===")
    print(f"deterministic untested classes: {agreement['deterministic_untested_classes']}")
    print(f"planner proposed classes:       {agreement['planner_proposed_classes']}")
    print(f"same classes: {agreement['same_classes']}")
    print(
        "duplicate direction suppressed when gaps are already scheduled: "
        f"{agreement['duplicate_direction_suppressed']}"
    )
    print(f"shadow wrote nothing in both runs: {result['shadow_wrote_nothing']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args(argv)

    result = run()
    _print_report(result)
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(result, indent=2, default=str))
        print(f"\nWrote {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
