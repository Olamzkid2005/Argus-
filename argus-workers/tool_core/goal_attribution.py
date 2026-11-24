"""Attribute the findings a worker produces to the intent and goal it serves.

A goal can only be concluded from a finding the verifier proved *and* that is
attributed to it (``orchestrator_pkg.persistence.goal_proof``). The attribution
therefore has to be created where the finding is produced: the intent worker
knows which goal its claimed intent was proposed for, so it stamps that goal on
its findings instead of leaving the save path to guess.

Explicit attribution always wins: a tool that already set ``goal_node_id`` on a
finding is never overwritten by the surrounding worker context.
"""

from __future__ import annotations

from typing import Any

#: Keys that tie a finding to the work that produced it.
ATTRIBUTION_KEYS = ("goal_node_id", "intent_node_id")


def stamp_goal_attribution(
    findings: list[Any],
    *,
    goal_node_id: str | None = "",
    intent_node_id: str | None = "",
) -> list[Any]:
    """Attach *goal_node_id*/*intent_node_id* to findings that lack one.

    The goal id is written both on the finding and (when it has an evidence
    dict) into ``evidence``: the evidence is what a later
    ``prove_goal_from_findings`` call can see in the stored row, while the
    top-level key is what the save hook sees in memory.

    Args:
        findings: Finding dicts produced by the tool run, modified in place.
        goal_node_id: Goal the claimed intent was proposed for.
        intent_node_id: Intent the worker held while running.

    Returns:
        The same list, so callers can use it inline.
    """
    if not findings:
        return findings

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if goal_node_id and not finding.get("goal_node_id"):
            finding["goal_node_id"] = goal_node_id
            evidence = finding.get("evidence")
            if isinstance(evidence, dict) and not evidence.get("goal_node_id"):
                evidence["goal_node_id"] = goal_node_id
        if intent_node_id and not finding.get("intent_node_id"):
            finding["intent_node_id"] = intent_node_id
    return findings
