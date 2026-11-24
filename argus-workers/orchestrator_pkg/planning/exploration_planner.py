"""
ARTEX ExplorationPlanner (proposal-only).

The planner reads a persisted overview of the engagement graph and returns typed
intent proposals. It never writes graph state: the dispatcher validates and
persists proposals under C-18 ownership.

Hard floor (plan section 3.5): if a goal is unmet and no intent is open or
running, the planner must propose at least one intent. It returns an empty list
only when there is genuinely nothing to do; the dispatcher turns an empty turn in
that state into a loud ``PlannerHardFloorError`` rather than a silent no-op.
"""

from __future__ import annotations

from typing import Any

from database.graph_intents import IntentProposal

DEFAULT_MAX_INTENTS = 5


class ExplorationPlanner:
    """Turn a planner overview into at most ``max_intents`` intent proposals."""

    def __init__(self, max_intents: int = DEFAULT_MAX_INTENTS) -> None:
        if max_intents < 1:
            raise ValueError("max_intents must be at least 1")
        self.max_intents = int(max_intents)

    def plan(self, overview: dict[str, Any]) -> list[IntentProposal]:
        unmet_goals = [
            goal
            for goal in overview.get("goals", [])
            if goal.get("state") != "concluded"
        ]
        if not unmet_goals:
            # Every operator goal is proven; planning has no work to add.
            return []

        open_intents = overview.get("open_intents", [])
        if open_intents:
            # A-09: open/running intents already cover the frontier.
            return []

        proposals: list[IntentProposal] = []
        active_goal = unmet_goals[0]
        for asset in overview.get("untested_assets", [])[: self.max_intents]:
            proposals.append(
                IntentProposal(
                    objective=(
                        f"test {asset['asset_type']} {asset['canonical_key']}"
                    ),
                    target_asset_ids=(str(asset["id"]),),
                    goal_node_id=str(active_goal["id"]),
                    priority=int(asset.get("priority") or 0),
                    rationale=(
                        "untested in-scope asset selected from the planner overview"
                    ),
                )
            )
        return proposals
