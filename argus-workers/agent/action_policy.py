"""Action identity, bounded revisits, stop decisions and coverage policy.

Stage 5.1 item 3. The loop used to deduplicate by tool name alone: once a tool
had run it was excluded forever, so a second, genuinely different use — a
different endpoint, the same endpoint as another identity, a payload justified
by a new finding — was impossible, while re-running the *exact* same call was
only prevented by that coarse name check. This module compares whole actions:

* an action signature is (tool, canonical arguments), so ``sqlmap --url A`` and
  ``sqlmap --url B`` are different actions;
* an identical signature is refused unless a new identity or new evidence
  justifies the revisit, and even then only up to a bounded count per tool;
* a stop decision is honoured only when the required coverage is complete —
  otherwise the run continues and says which capability is still missing.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass


def _canonical(value):
    """Stable JSON representation: dict order irrelevant, values stringified."""
    if isinstance(value, dict):
        return {str(key): _canonical(val) for key, val in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def action_signature(tool: str, arguments: dict | None) -> str:
    """Identity of an action: the tool plus every argument that shaped it."""
    payload = json.dumps(
        {"tool": tool, "arguments": _canonical(arguments or {})},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_action(
    signatures: dict[str, str],
    tool_counts: dict[str, int],
    tool: str,
    arguments: dict | None,
    *,
    max_revisits_per_tool: int = 2,
    new_identity: bool = False,
    new_evidence: bool = False,
) -> ActionDecision:
    """Decide whether an action may run, given previously issued signatures.

    Shared by the in-process agent and the MCP session store so both apply the
    same rule: whole-action identity, bounded revisits, and an explicit reason.
    """
    signature = action_signature(tool, arguments)
    runs = int(tool_counts.get(tool, 0))

    if signature in signatures:
        if not (new_identity or new_evidence):
            return ActionDecision(
                allowed=False,
                reason=(
                    f"duplicate action: {tool} with these exact arguments already ran; "
                    "a new identity, new evidence or different arguments are required"
                ),
                signature=signature,
            )
        if runs >= max_revisits_per_tool + 1:
            return ActionDecision(
                allowed=False,
                reason=(
                    f"revisit limit reached for {tool}: {runs} run(s) already executed "
                    f"(max {max_revisits_per_tool} revisit(s))"
                ),
                signature=signature,
            )
        return ActionDecision(
            allowed=True,
            reason="revisit justified by new identity or evidence",
            revisit=True,
            signature=signature,
        )

    if runs > max_revisits_per_tool:
        return ActionDecision(
            allowed=False,
            reason=(
                f"revisit limit reached for {tool}: {runs} run(s) already executed "
                f"(max {max_revisits_per_tool} revisit(s))"
            ),
            signature=signature,
        )

    return ActionDecision(
        allowed=True,
        reason="new action",
        revisit=runs > 0,
        signature=signature,
    )


@dataclass(frozen=True)
class ActionDecision:
    allowed: bool
    reason: str
    revisit: bool = False
    signature: str = ""


class ActionPolicy:
    """Bounded, signature-based permission to run another action."""

    def __init__(self, max_revisits_per_tool: int = 2) -> None:
        self.max_revisits_per_tool = max_revisits_per_tool
        self._signatures: dict[str, str] = {}
        self._tool_runs: Counter[str] = Counter()
        self._executed_tools: list[str] = []

    # ── Queries ────────────────────────────────────────────────────────
    @property
    def executed_tools(self) -> list[str]:
        return list(self._executed_tools)

    def signatures(self) -> dict[str, str]:
        return dict(self._signatures)

    def tool_runs(self, tool: str) -> int:
        return self._tool_runs[tool]

    # ── Decisions ──────────────────────────────────────────────────────
    def check(
        self,
        tool: str,
        arguments: dict | None,
        *,
        new_identity: bool = False,
        new_evidence: bool = False,
    ) -> ActionDecision:
        """Whether this action may run now, and why."""
        return check_action(
            self._signatures,
            dict(self._tool_runs),
            tool,
            arguments,
            max_revisits_per_tool=self.max_revisits_per_tool,
            new_identity=new_identity,
            new_evidence=new_evidence,
        )

    def record(self, tool: str, arguments: dict | None) -> str:
        """Remember that an action ran; returns its signature."""
        signature = action_signature(tool, arguments)
        self._signatures[signature] = tool
        self._tool_runs[tool] += 1
        self._executed_tools.append(tool)
        return signature


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: str
    missing: tuple[str, ...] = ()


class CoveragePolicy:
    """Which capabilities must run before the assessment may stop."""

    def __init__(self, required: Iterable[str] | None = None) -> None:
        self.required = {str(item) for item in (required or []) if str(item)}

    def missing(self, executed: Iterable[str]) -> list[str]:
        executed_set = set(executed)
        return sorted(self.required - executed_set)

    def can_stop(self, requested_stop: bool, executed: Iterable[str]) -> StopDecision:
        """Honour a stop only when required coverage is complete.

        When coverage is missing the run continues, but the decision is
        explicit: the caller can log the missing capabilities instead of
        silently overriding the stop.
        """
        missing = self.missing(executed)
        if requested_stop and missing:
            return StopDecision(
                stop=False,
                reason=f"stop deferred: required coverage missing ({', '.join(missing)})",
                missing=tuple(missing),
            )
        if requested_stop:
            return StopDecision(stop=True, reason="stop decision honoured; required coverage complete")
        return StopDecision(stop=False, reason="continue")
