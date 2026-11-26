"""Specialist roles and capabilities for bounded delegation (plan §4.6).

Roles mirror the upstream specialist set. Registration is capability based, so the
Primary Agent can activate only the specialists a subtask actually needs instead
of launching the whole swarm for every step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

PENTESTER = "pentester"
CODER = "coder"
INSTALLER = "installer"
SEARCHER = "searcher"
ADVISER = "adviser"
MEMORIST = "memorist"
ENRICHER = "enricher"
REPORTER = "reporter"

SPECIALIST_ROLES = (
    PENTESTER,
    CODER,
    INSTALLER,
    SEARCHER,
    ADVISER,
    MEMORIST,
    ENRICHER,
    REPORTER,
)


@runtime_checkable
class SpecialistRunner(Protocol):
    """A specialist agent. It receives one bounded request and mutates nothing."""

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class Specialist:
    role: str
    capabilities: frozenset[str]
    runner: SpecialistRunner
    description: str = ""


@dataclass
class SpecialistRegistry:
    """Role/capability lookup for the Primary Agent."""

    _specialists: dict[str, Specialist] = field(default_factory=dict)

    def register(
        self,
        role: str,
        capabilities: frozenset[str] | set[str] | tuple[str, ...],
        runner: SpecialistRunner,
        *,
        description: str = "",
    ) -> Specialist:
        if not role:
            raise ValueError("specialist role is required")
        specialist = Specialist(
            role=role,
            capabilities=frozenset(capabilities),
            runner=runner,
            description=description,
        )
        self._specialists[role] = specialist
        return specialist

    def get(self, role: str) -> Specialist | None:
        return self._specialists.get(role)

    def roles(self) -> tuple[str, ...]:
        return tuple(sorted(self._specialists))

    def specialists_for(self, capabilities: frozenset[str] | set[str]) -> list[Specialist]:
        """Return registered specialists that cover any requested capability."""
        wanted = set(capabilities)
        return [
            specialist
            for _, specialist in sorted(self._specialists.items())
            if specialist.capabilities & wanted
        ]

    def capabilities(self) -> frozenset[str]:
        return frozenset().union(
            *(specialist.capabilities for specialist in self._specialists.values())
        )
