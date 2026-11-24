"""Conclude graph goals from findings the verifier itself proved (A-08).

A goal is only ever concluded through ``prove_goal_from_findings``, which checks
that the finding row is CONFIRMED/VERIFIED *and* carries verifier provenance.
That check is the guarantee; this module is the caller that makes it happen in
the real pipeline instead of only in an operator's explicit dispatcher call.

Attribution is explicit. A producer that knows which goal its work serves stamps
``goal_node_id`` or ``proves_goal_ids`` on the finding (or its evidence), and only
those goals are concluded. With no attribution, a single-objective engagement —
one open goal, the normal case — is attributed to that goal; when several goals
are open the finding proves none of them, because guessing would let a reproduced
information leak conclude an RCE objective.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Where a finding may name the goal(s) its proof satisfies.
ATTRIBUTION_KEYS = ("goal_node_id", "proves_goal_ids")

_TERMINAL_PROVEN = ("CONFIRMED", "VERIFIED")


def attributed_goal_ids(finding: dict) -> list[str]:
    """Return the goal ids *finding* explicitly claims to prove, deduplicated."""
    evidence = finding.get("evidence") or {}
    found: list[str] = []
    for source in (finding, evidence):
        if not isinstance(source, dict):
            continue
        single = source.get("goal_node_id")
        if isinstance(single, str) and single:
            found.append(single)
        many = source.get("proves_goal_ids")
        if isinstance(many, (list, tuple)):
            found.extend(g for g in many if isinstance(g, str) and g)
    return list(dict.fromkeys(found))


def conclude_proven_goals(
    engagement_id: str,
    findings: list[dict],
    *,
    dispatcher: Any | None = None,
) -> dict[str, Any]:
    """Conclude the goals that the just-saved, verifier-proven findings prove.

    Only findings with a saved row, a terminal verified status and (by way of
    ``prove_goal_from_findings``) verifier provenance are used. A graph failure
    never fails the caller: a scan must not fail because a goal could not be
    concluded, and the finding is already persisted.

    Args:
        engagement_id: Engagement whose graph holds the goals.
        findings: Finding dicts that went through the persistence service; each
            carries ``_saved_id`` after a successful write.
        dispatcher: Optional ``DispatcherGraph`` (tests, or an existing owner).

    Returns:
        Summary with the goals concluded, the ones skipped and why, and the
        failures. Safe to log.
    """
    summary: dict[str, Any] = {
        "concluded": [],
        "skipped": [],
        "failed": [],
    }
    if not engagement_id or not findings:
        return summary

    by_finding = {
        str(f["_saved_id"]): f
        for f in findings
        if f.get("_saved_id")
        and str(f.get("status") or "").upper() in _TERMINAL_PROVEN
    }
    if not by_finding:
        return summary

    try:
        if dispatcher is None:
            from database.dispatcher_graph import DispatcherGraph
            from database.graph_repository import ExplorationGraphRepository

            dispatcher = DispatcherGraph(ExplorationGraphRepository())
        overview = dispatcher.planner_overview(engagement_id)
    except Exception as exc:  # graph unreachable/missing must not fail a scan
        logger.debug(
            "Goal proof skipped for %s: graph unavailable (%s)", engagement_id, exc
        )
        summary["skipped"].append({"reason": "graph_unavailable"})
        return summary

    open_goals = [
        goal for goal in overview.get("goals", []) if goal.get("state") != "concluded"
    ]
    if not open_goals:
        return summary
    open_goal_ids = {str(goal["id"]) for goal in open_goals}

    # finding id -> goal ids it may prove
    eligible: dict[str, list[str]] = {}
    for finding_id, finding in by_finding.items():
        explicit = attributed_goal_ids(finding)
        attributed = [goal for goal in explicit if goal in open_goal_ids]
        if not attributed:
            if explicit:
                # The finding named goals that are not this engagement's open
                # goals (another engagement's, already concluded, or a typo).
                # A wrong attribution is not a licence to guess.
                summary["skipped"].append(
                    {
                        "finding_id": finding_id,
                        "reason": "unknown_goal",
                        "attributed": explicit,
                    }
                )
                continue
            if len(open_goal_ids) == 1:
                # Single-objective engagement: the one open goal is the work.
                attributed = list(open_goal_ids)
            else:
                summary["skipped"].append(
                    {
                        "finding_id": finding_id,
                        "reason": "unattributed",
                        "open_goals": sorted(open_goal_ids),
                    }
                )
                continue
        eligible.setdefault(finding_id, attributed)

    # goal id -> finding ids proving it
    by_goal: dict[str, list[str]] = {}
    for finding_id, goal_ids in eligible.items():
        for goal_id in goal_ids:
            by_goal.setdefault(goal_id, []).append(finding_id)

    for goal_id, finding_ids in by_goal.items():
        try:
            proven = dispatcher.prove_goal_from_findings(
                engagement_id,
                goal_id,
                finding_ids,
                proof_summary="confirmed by the verification pipeline",
            )
        except Exception as exc:  # GraphMutationError or storage failure
            logger.warning(
                "Could not conclude goal %s from finding(s) %s: %s",
                goal_id,
                ", ".join(finding_ids),
                exc,
            )
            summary["failed"].append(
                {"goal_id": goal_id, "finding_ids": finding_ids, "error": str(exc)}
            )
            continue

        logger.info(
            "Goal %s concluded by verifier-confirmed finding(s) %s",
            goal_id,
            ", ".join(finding_ids),
        )
        summary["concluded"].append(
            {
                "goal_id": goal_id,
                "finding_ids": finding_ids,
                "goal": proven.get("goal") if isinstance(proven, dict) else None,
            }
        )

    return summary
