"""Parity guard: phases.py must match state_machine.EngagementStateMachine.

phases.py declares itself the single source of truth for the engagement
lifecycle and its TRANSITIONS comment states the dict "MUST match
state_machine.py EngagementStateMachine.TRANSITIONS". The two are separate
declarations (deliberately, to avoid a circular import), so nothing stops
them from drifting — which is exactly what happened when the
`source_analysis` phase was added to phases.py only.

These tests fail loudly on any future drift instead of letting an
invalid state reach the database at runtime.
"""

from __future__ import annotations

from phases import PHASES, get_phase
from phases import TRANSITIONS as PHASE_TRANSITIONS
from state_machine import EngagementStateMachine, resolve_state_for_phase


class TestPhaseStateMachineParity:
    """phases.py and EngagementStateMachine must describe the same lifecycle."""

    def test_declared_states_match(self):
        phase_ids = {p.id for p in PHASES}
        sm_states = set(EngagementStateMachine.STATES)
        assert phase_ids == sm_states, (
            "phases.py and state_machine.STATES declare different lifecycle "
            f"states. phases.py only: {sorted(phase_ids - sm_states)}; "
            f"state_machine.py only: {sorted(sm_states - phase_ids)}"
        )

    def test_transition_keys_match(self):
        assert set(PHASE_TRANSITIONS.keys()) == set(
            EngagementStateMachine.TRANSITIONS.keys()
        ), "TRANSITIONS has different source states in the two modules"

    def test_transition_targets_match(self):
        for state, targets in PHASE_TRANSITIONS.items():
            sm_targets = EngagementStateMachine.TRANSITIONS.get(state)
            assert sm_targets is not None, f"{state!r} missing from state machine"
            assert set(targets) == set(sm_targets), (
                f"Transition targets for {state!r} differ. "
                f"phases.py only: {sorted(set(targets) - set(sm_targets))}; "
                f"state_machine.py only: {sorted(set(sm_targets) - set(targets))}"
            )

    def test_every_phase_resolves_to_itself(self):
        """Each lifecycle phase id must be accepted as a state machine state."""
        for phase in PHASES:
            assert resolve_state_for_phase(phase.id) == phase.id, (
                f"resolve_state_for_phase({phase.id!r}) did not map to itself — "
                "the phase is not a valid state machine state"
            )

    def test_source_analysis_is_a_first_class_state(self):
        """Regression: `source_analysis` is a real tool phase (tool_definitions
        ALL_PHASES + the `ai-surface` tool declare it), so it must exist as a
        lifecycle state and be reachable from recon."""
        assert get_phase("source_analysis") is not None
        assert "source_analysis" in EngagementStateMachine.STATES
        assert "source_analysis" in EngagementStateMachine.TRANSITIONS["recon"]
        assert "source_analysis" in PHASE_TRANSITIONS["recon"]
