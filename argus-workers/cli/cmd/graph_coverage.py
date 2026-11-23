"""Graph coverage command — computed ARTEX coverage against the approved scope."""

from __future__ import annotations

import argparse
import json
import os


def cmd_graph_coverage(args: argparse.Namespace) -> int:
    """
    Report discovered assets vs ``engagements.authorized_scope`` for a scope.

    Unlike an anchor lookup, this compares what recon actually discovered with
    what the operator approved: coverage gaps (approved but undiscovered),
    out-of-scope discoveries (flagged or rejected), and untested asset classes.
    """
    engagement_id = getattr(args, "engagement", None)
    if not engagement_id:
        print("--engagement is required")
        return 2
    if not os.getenv("DATABASE_URL"):
        print(
            "DATABASE_URL must be set: graph coverage reads the PostgreSQL "
            "graph tables."
        )
        return 2

    from database.dispatcher_graph import DispatcherGraph
    from database.graph_repository import ExplorationGraphRepository

    dispatcher = DispatcherGraph(ExplorationGraphRepository())
    try:
        report = dispatcher.coverage_report(engagement_id)
    except Exception as exc:  # noqa: BLE001 - surface as a CLI failure
        print(f"Graph coverage failed: {exc}")
        return 1

    if getattr(args, "schedule", False):
        try:
            report["scheduled_work"] = dispatcher.schedule_coverage_gaps(
                engagement_id
            )
        except Exception as exc:  # noqa: BLE001 - surface as a CLI failure
            print(f"Coverage gap scheduling failed: {exc}")
            return 1

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(
        f"Scope {report['scope_id']} "
        f"(authorized scope checked: {report['authorized_scope_checked']})"
    )
    print(
        f"Discovered assets: {report['assets_total']} "
        f"(in scope {report['assets_in_scope']}, "
        f"out of scope {report['assets_out_of_scope']})"
    )
    print(
        f"Covered: {report['assets_covered']}  "
        f"Untested: {report['assets_untested']}"
    )
    if report["untested_asset_types"]:
        print("Untested asset classes: " + ", ".join(report["untested_asset_types"]))
    if report["undiscovered_asset_types"]:
        print(
            "Undiscovered asset classes: "
            + ", ".join(report["undiscovered_asset_types"])
        )

    print("Approved but undiscovered:")
    gaps = report["approved_but_undiscovered"]
    for gap in gaps:
        print(f"  - {gap['kind']}: {gap['value']}")
    if not gaps:
        print("  (none)")

    print("Discovered but unapproved:")
    unapproved = report["discovered_but_unapproved"]
    for asset in unapproved:
        print(f"  - {asset['asset_type']}: {asset['canonical_key']}")
    if not unapproved:
        print("  (none)")

    print(
        f"Rejected out-of-scope observations: "
        f"{report['rejected_observation_count']}"
    )
    for observation in report["rejected_observations"][:10]:
        print(
            f"  - {observation['asset_type']}: {observation['observed_value']} "
            f"({observation['source']}, {observation['rejection_reason']})"
        )

    scheduled_work = report.get("scheduled_work")
    if scheduled_work is not None:
        print(
            f"Scheduled recon work: {scheduled_work['scheduled_count']} "
            f"new todo(s), {scheduled_work['already_scheduled']} already scheduled"
        )
        for entry in scheduled_work["scheduled"]:
            print(f"  - {entry['gap_type']}: {entry['gap_key']} (todo {entry['todo_id']})")
    return 0
