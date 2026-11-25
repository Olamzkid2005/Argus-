"""
Typed IntentProposal contract for graph planning (A3).

The planner is a proposal generator: it returns ``IntentProposal`` objects and
the dispatcher validates and persists them. Validation lives here so an invalid
proposal is rejected on the way in, before any graph mutation, and the derived
``intent_key`` gives duplicate suppression a stable identity.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

MAX_OBJECTIVE_LENGTH = 500
MAX_RATIONALE_LENGTH = 2000
MAX_TARGET_ASSETS = 25
MAX_FROM_FACTS = 50
MAX_PRIORITY = 100


class IntentProposalError(ValueError):
    """A planner proposal does not satisfy the typed contract."""


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class IntentProposal:
    """One typed intent proposal from the planner."""

    objective: str
    target_asset_ids: tuple[str, ...] = ()
    from_fact_ids: tuple[str, ...] = ()
    goal_node_id: str | None = None
    priority: int = 0
    rationale: str = ""

    def validated(self) -> IntentProposal:
        """Return a normalized copy or raise :class:`IntentProposalError`."""
        if not isinstance(self.objective, str):
            raise IntentProposalError("objective must be a string")
        objective = " ".join(self.objective.split())
        if not objective:
            raise IntentProposalError("objective is required")
        if len(objective) > MAX_OBJECTIVE_LENGTH:
            raise IntentProposalError(
                f"objective exceeds {MAX_OBJECTIVE_LENGTH} characters"
            )
        if not isinstance(self.rationale, str):
            raise IntentProposalError("rationale must be a string")
        if len(self.rationale) > MAX_RATIONALE_LENGTH:
            raise IntentProposalError(
                f"rationale exceeds {MAX_RATIONALE_LENGTH} characters"
            )

        targets = tuple(dict.fromkeys(str(value) for value in self.target_asset_ids))
        if not targets:
            raise IntentProposalError("at least one target_asset_id is required")
        if len(targets) > MAX_TARGET_ASSETS:
            raise IntentProposalError(
                f"at most {MAX_TARGET_ASSETS} target assets are allowed"
            )
        for target in targets:
            if not _is_uuid(target):
                raise IntentProposalError(f"target_asset_id is not a UUID: {target}")

        from_facts = tuple(dict.fromkeys(str(value) for value in self.from_fact_ids))
        if len(from_facts) > MAX_FROM_FACTS:
            raise IntentProposalError(
                f"at most {MAX_FROM_FACTS} source facts are allowed"
            )
        for fact_id in from_facts:
            if not _is_uuid(fact_id):
                raise IntentProposalError(f"from_fact_id is not a UUID: {fact_id}")

        if self.goal_node_id is not None and not _is_uuid(str(self.goal_node_id)):
            raise IntentProposalError("goal_node_id is not a UUID")

        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise IntentProposalError("priority must be an integer")
        if not 0 <= self.priority <= MAX_PRIORITY:
            raise IntentProposalError(
                f"priority must be between 0 and {MAX_PRIORITY}"
            )

        return IntentProposal(
            objective=objective,
            target_asset_ids=targets,
            from_fact_ids=from_facts,
            goal_node_id=str(self.goal_node_id) if self.goal_node_id else None,
            priority=self.priority,
            rationale=self.rationale,
        )

    def intent_key(self) -> str:
        """Stable identity for duplicate suppression (objective + targets + facts)."""
        proposal = self.validated()
        material = "|".join(
            [
                proposal.objective.lower(),
                ",".join(sorted(proposal.target_asset_ids)),
                ",".join(sorted(proposal.from_fact_ids)),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def to_payload(self) -> dict:
        """JSON-serializable node payload for the persisted intent."""
        proposal = self.validated()
        return {
            "objective": proposal.objective,
            "intent_key": proposal.intent_key(),
            "target_asset_ids": list(proposal.target_asset_ids),
            "from_fact_ids": list(proposal.from_fact_ids),
            "goal_node_id": proposal.goal_node_id,
            "rationale": proposal.rationale,
            "origin": "planner",
        }
