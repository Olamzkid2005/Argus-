"""
Phase Model — single source of truth for engagement lifecycle.

Consolidates phase/state definitions that were previously scattered across:
  - state_machine.py (STATES, TRANSITIONS)
  - agent_loop.py (PHASE_AGENTS)
  - useScanEstimates.ts (STATE_ORDER, BASE_ESTIMATES)

Any change to phases (add, rename, reorder, remove) should edit ONLY this file.

Usage:
    from phases import PHASES, TRANSITIONS, get_phase, is_valid_transition
    phase = get_phase("scanning")
    print(phase.display_name)  # "Scanning"
    print(phase.estimated_minutes)  # 10
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Phase:
    """A single phase in the engagement lifecycle."""

    #: Canonical ID (used in database, API, state machine)
    id: str

    #: Human-readable label (used in frontend)
    display_name: str

    #: Display order (for progress bars, timelines)
    order: int

    #: Estimated duration in minutes (for frontend estimates)
    estimated_minutes: int = 0

    #: Whether this is a terminal state
    is_terminal: bool = False

    #: Whether this is an error state
    is_error: bool = False

    #: Frontend phase step ID (for useScanEstimates compat)
    step_id: str | None = None

    #: Tool phases from agent_loop.py that map to this state
    tool_phases: tuple[str, ...] = field(default_factory=tuple)


# ═══════════════════════════════════════════════════════════════
# Phase definitions — single source of truth
# ═══════════════════════════════════════════════════════════════

PHASES: list[Phase] = [
    Phase(
        id="created",
        display_name="Created",
        order=0,
    ),
    Phase(
        id="recon",
        display_name="Reconnaissance",
        order=1,
        estimated_minutes=5,
        step_id="recon",
        tool_phases=("recon",),
    ),
    Phase(
        id="scanning",
        display_name="Scanning",
        order=2,
        estimated_minutes=10,
        step_id="vuln_mapping",
        tool_phases=("scan", "deep_scan", "repo_scan"),
    ),
    Phase(
        id="analyzing",
        display_name="Analysis",
        order=3,
        estimated_minutes=5,
        tool_phases=("analyze",),
    ),
    Phase(
        id="reporting",
        display_name="Report Generation",
        order=4,
        estimated_minutes=2,
        step_id="reporting",
        tool_phases=("report",),
    ),
    Phase(
        id="complete",
        display_name="Complete",
        order=5,
        is_terminal=True,
    ),
    Phase(
        id="failed",
        display_name="Failed",
        order=-1,
        is_error=True,
        is_terminal=True,
    ),
    Phase(
        id="paused",
        display_name="Paused",
        order=-1,
    ),
]

# ═══════════════════════════════════════════════════════════════
# State transitions
# ═══════════════════════════════════════════════════════════════

# NOTE: This dict MUST match state_machine.py EngagementStateMachine.TRANSITIONS.
# If you add/remove a transition, update both files. They are intentionally
# kept as separate declarations (not an import from state_machine) to avoid
# circular imports — phases.py is imported by frontend build tooling that
# does not import the full state machine module.
TRANSITIONS: dict[str, list[str]] = {
    "created": ["recon", "failed", "paused"],
    "recon": ["scanning", "failed", "paused"],
    "scanning": ["analyzing", "failed", "paused"],
    "analyzing": ["reporting", "recon", "scanning", "failed", "paused"],
    "reporting": ["complete", "failed", "paused"],
    "paused": ["recon", "scanning", "analyzing"],
    "failed": [],
    "complete": [],
}

# ═══════════════════════════════════════════════════════════════
# Derived lookup structures
# ═══════════════════════════════════════════════════════════════

#: Quick ID → Phase lookup
_PHASE_MAP: dict[str, Phase] = {p.id: p for p in PHASES}


def get_phase(phase_id: str) -> Phase | None:
    """Get a phase definition by its canonical ID.

    Args:
        phase_id: Phase ID (e.g., "scanning", "recon").

    Returns:
        Phase object if found, None otherwise.
    """
    return _PHASE_MAP.get(phase_id)


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is valid.

    Args:
        from_state: Current state ID.
        to_state: Target state ID.

    Returns:
        True if the transition is valid.
    """
    return to_state in TRANSITIONS.get(from_state, [])


def get_phase_order(phase_id: str) -> int:
    """Get the display order for a phase (for frontend progress bars).

    Returns -1 for non-initialized/unknown phases.

    Args:
        phase_id: Phase ID.

    Returns:
        Numerical order value.
    """
    phase = _PHASE_MAP.get(phase_id)
    return phase.order if phase else -1


def get_phase_by_step_id(step_id: str) -> Phase | None:
    """Find a phase by its frontend step_id (for useScanEstimates compat).

    Args:
        step_id: Frontend step identifier.

    Returns:
        Phase object if found.
    """
    for phase in PHASES:
        if phase.step_id == step_id:
            return phase
    return None


def get_phases_for_tool_phase(tool_phase: str) -> list[Phase]:
    """Get phases that map to a given tool phase from agent_loop.py.

    Args:
        tool_phase: Tool phase name (e.g., "scan", "recon").

    Returns:
        List of matching Phase objects.
    """
    return [p for p in PHASES if tool_phase in p.tool_phases]


def to_json_serializable() -> list[dict]:
    """Export phases as a JSON-serializable list (for frontend consumption).

    Returns:
        List of phase dicts with id, display_name, order, estimated_minutes.
    """
    return [
        {
            "id": p.id,
            "display_name": p.display_name,
            "order": p.order,
            "estimated_minutes": p.estimated_minutes,
            "is_terminal": p.is_terminal,
            "is_error": p.is_error,
        }
        for p in PHASES
    ]
