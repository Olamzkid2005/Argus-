"""Reflector: bounded repair of unstructured agent output (plan §4.8).

A structured tool call/result is required. When the agent returns something the
parser cannot read, the Reflector asks for a correction at most three times,
preserving the same subtask/session context. If it still cannot parse, the
failure is explicit: callers mark the subtask FAILED or WAITING, never finished.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agent.delegation.models import ReflectionExhausted

MAX_REFLECTION_ATTEMPTS = 3


class RepairAgent(Protocol):
    """An agent that rewrites invalid output into the required structure."""

    def repair(self, invalid_output: Any, context: dict[str, Any]) -> Any:
        ...


@dataclass(frozen=True)
class ReflectionOutcome:
    value: Any
    attempts: int
    repaired: bool


class Reflector:
    """Run parse -> repair up to ``max_attempts`` times (default 3)."""

    def __init__(
        self,
        repair_agent: RepairAgent | None = None,
        *,
        max_attempts: int = MAX_REFLECTION_ATTEMPTS,
    ) -> None:
        if max_attempts < 0:
            raise ValueError("max_attempts cannot be negative")
        self._agent = repair_agent
        self.max_attempts = max_attempts

    def parse_or_repair(
        self,
        output: Any,
        parser: Callable[[Any], Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> ReflectionOutcome:
        """Return the first parseable value or raise ``ReflectionExhausted``."""
        context = dict(context or {})
        attempts = 0
        current = output
        last_error: Exception | None = None
        while True:
            try:
                return ReflectionOutcome(
                    value=parser(current),
                    attempts=attempts,
                    repaired=attempts > 0,
                )
            except Exception as exc:  # the parser defines what is invalid
                last_error = exc
            if attempts >= self.max_attempts or self._agent is None:
                raise ReflectionExhausted(
                    f"structured output still invalid after {attempts} repair "
                    f"attempt(s): {last_error}",
                    attempts=attempts,
                ) from last_error
            attempts += 1
            current = self._agent.repair(current, {**context, "attempt": attempts})
