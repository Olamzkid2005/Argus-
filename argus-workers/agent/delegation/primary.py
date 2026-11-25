"""Primary Agent and bounded specialist delegation (plan §4.6).

The Primary Agent handles one subtask. It may call specialists through a typed
interface, but it never receives the delegation store: specialists and the
Primary Agent return structured results, and only the delegation service
persists them. Conflicting specialist findings are surfaced for the
verifier/correlation layer instead of being silently resolved here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.delegation.models import DelegationError
from agent.delegation.registry import SpecialistRegistry

#: Bounded context: the specialist receives at most this much of each input.
MAX_FACTS = 10
MAX_TARGETS = 25
MAX_TOOLS = 40


@dataclass(frozen=True)
class SpecialistRequest:
    """The complete, bounded payload a specialist is allowed to see."""

    role: str
    engagement_id: str
    subtask_id: str
    objective: str
    description: str
    dependencies: tuple[str, ...] = ()
    facts: tuple[dict[str, Any], ...] = ()
    authorized_targets: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "engagement_id": self.engagement_id,
            "subtask_id": self.subtask_id,
            "objective": self.objective,
            "description": self.description,
            "dependencies": list(self.dependencies),
            "facts": [dict(fact) for fact in self.facts],
            "authorized_targets": list(self.authorized_targets),
            "allowed_tools": list(self.allowed_tools),
        }


@dataclass(frozen=True)
class SpecialistResult:
    """A specialist's structured output; it changes no task or graph state."""

    role: str
    status: str
    summary: str
    findings: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_agent: str | None = None

    @classmethod
    def from_payload(cls, role: str, payload: Any) -> SpecialistResult:
        if not isinstance(payload, dict):
            raise DelegationError(
                f"specialist {role!r} returned {type(payload).__name__}, not an object"
            )
        status = str(payload.get("status") or "ok")
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise DelegationError(f"specialist {role!r} returned no summary")
        findings = payload.get("findings") or []
        if not isinstance(findings, (list, tuple)):
            raise DelegationError(f"specialist {role!r} findings must be a list")
        if any(not isinstance(finding, dict) for finding in findings):
            raise DelegationError(
                f"specialist {role!r} findings must be objects, not bare values"
            )
        refs = payload.get("evidence_refs") or []
        if not isinstance(refs, (list, tuple)):
            raise DelegationError(f"specialist {role!r} evidence_refs must be a list")
        return cls(
            role=role,
            status=status,
            summary=summary.strip(),
            findings=tuple(dict(finding) for finding in findings),
            evidence_refs=tuple(str(ref) for ref in refs),
            source_agent=payload.get("source_agent") or role,
        )

    @property
    def failed(self) -> bool:
        return self.status.lower() not in ("ok", "success", "completed")


@dataclass(frozen=True)
class PrimaryOutcome:
    summary: str
    specialist_results: tuple[SpecialistResult, ...] = ()
    merged_findings: tuple[dict[str, Any], ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    provenance: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def as_result(self) -> dict[str, Any]:
        """The structured payload the delegation service persists (not the agent)."""
        return {
            "summary": self.summary,
            "findings": [dict(finding) for finding in self.merged_findings],
            "conflicts": [dict(conflict) for conflict in self.conflicts],
            "provenance": [dict(entry) for entry in self.provenance],
            "specialists": [result.role for result in self.specialist_results],
            "evidence_refs": sorted(
                {
                    ref
                    for result in self.specialist_results
                    for ref in result.evidence_refs
                }
            ),
        }


def _finding_key(finding: dict[str, Any]) -> tuple[str, str]:
    return (
        str(finding.get("asset") or finding.get("target") or finding.get("endpoint") or ""),
        str(finding.get("type") or finding.get("title") or ""),
    )


class PrimaryAgent:
    """Delegates one subtask to capability-matched specialists and merges results."""

    def __init__(
        self,
        registry: SpecialistRegistry,
        *,
        max_facts: int = MAX_FACTS,
        max_targets: int = MAX_TARGETS,
        max_tools: int = MAX_TOOLS,
    ) -> None:
        self._registry = registry
        self.max_facts = max_facts
        self.max_targets = max_targets
        self.max_tools = max_tools

    def handle(
        self,
        subtask: dict[str, Any],
        *,
        capabilities: frozenset[str] | set[str],
        facts: list[dict[str, Any]] | None = None,
        authorized_targets: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        engagement_id: str = "",
    ) -> PrimaryOutcome:
        specialists = self._registry.specialists_for(capabilities)
        if not specialists:
            raise DelegationError(
                "no registered specialist covers capabilities "
                + ", ".join(sorted(capabilities))
            )

        results: list[SpecialistResult] = []
        for specialist in specialists:
            request = SpecialistRequest(
                role=specialist.role,
                engagement_id=engagement_id,
                subtask_id=str(subtask.get("id") or ""),
                objective=str(subtask.get("title") or ""),
                description=str(subtask.get("description") or ""),
                dependencies=tuple(
                    str(dep) for dep in (subtask.get("depends_on") or [])
                ),
                facts=tuple((facts or [])[: self.max_facts]),
                authorized_targets=tuple(
                    (authorized_targets or [])[: self.max_targets]
                ),
                allowed_tools=tuple((allowed_tools or [])[: self.max_tools]),
            )
            results.append(
                SpecialistResult.from_payload(
                    specialist.role, specialist.runner.run(request.as_payload())
                )
            )

        merged: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        seen: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for result in results:
            for finding in result.findings:
                entry = dict(finding)
                entry["source_agent"] = result.source_agent or result.role
                merged.append(entry)
                seen.setdefault(_finding_key(entry), []).append(entry)

        for key, entries in seen.items():
            verdicts = {
                str(
                    entry.get("severity")
                    or entry.get("status")
                    or entry.get("conclusion")
                    or ""
                )
                for entry in entries
            }
            if len(verdicts) > 1:
                conflicts.append(
                    {
                        "asset": key[0],
                        "type": key[1],
                        "values": sorted(verdicts),
                        "resolution": "requires_verification",
                        "sources": [entry["source_agent"] for entry in entries],
                    }
                )

        provenance = tuple(
            {
                "role": result.role,
                "source_agent": result.source_agent or result.role,
                "status": result.status,
                "findings": len(result.findings),
                "evidence_refs": list(result.evidence_refs),
            }
            for result in results
        )
        summary = " | ".join(result.summary for result in results)
        return PrimaryOutcome(
            summary=summary,
            specialist_results=tuple(results),
            merged_findings=tuple(merged),
            conflicts=tuple(conflicts),
            provenance=provenance,
        )
