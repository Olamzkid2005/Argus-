"""Tests for phases.py

Covers:
  - Phase dataclass fields and defaults
  - PHASES list completeness and ordering
  - TRANSITIONS dict correctness
  - get_phase lookup
  - is_valid_transition
  - get_phase_order
  - get_phase_by_step_id
  - get_phases_for_tool_phase
  - to_json_serializable
"""

from __future__ import annotations

from phases import (
    PHASES,
    TRANSITIONS,
    Phase,
    get_phase,
    get_phase_by_step_id,
    get_phase_order,
    get_phases_for_tool_phase,
    is_valid_transition,
    to_json_serializable,
)


class TestPhaseDataclass:
    """Tests for the Phase dataclass."""

    def test_default_values(self):
        phase = Phase(id="test", display_name="Test", order=0)
        assert phase.estimated_minutes == 0
        assert phase.is_terminal is False
        assert phase.is_error is False
        assert phase.step_id is None
        assert phase.tool_phases == ()

    def test_full_construction(self):
        phase = Phase(
            id="scanning",
            display_name="Scanning",
            order=2,
            estimated_minutes=10,
            is_terminal=False,
            is_error=False,
            step_id="vuln_mapping",
            tool_phases=("scan", "deep_scan", "repo_scan"),
        )
        assert phase.id == "scanning"
        assert phase.display_name == "Scanning"
        assert phase.order == 2
        assert phase.estimated_minutes == 10
        assert phase.step_id == "vuln_mapping"
        assert "scan" in phase.tool_phases


class TestPHASES:
    """Tests for the PHASES list."""

    def test_has_all_expected_phases(self):
        ids = [p.id for p in PHASES]
        assert "created" in ids
        assert "recon" in ids
        assert "scanning" in ids
        assert "analyzing" in ids
        assert "reporting" in ids
        assert "complete" in ids
        assert "failed" in ids
        assert "paused" in ids
        assert len(ids) == 8

    def test_terminal_phases(self):
        complete = get_phase("complete")
        failed = get_phase("failed")
        assert complete is not None
        assert failed is not None
        assert complete.is_terminal is True
        assert failed.is_terminal is True
        assert failed.is_error is True

    def test_order_values(self):
        for p in PHASES:
            if p.id == "complete":
                assert p.order == 5
            elif p.id == "recon":
                assert p.order == 1
            elif p.id == "scanning":
                assert p.order == 2
            elif p.id in ("failed", "paused"):
                assert p.order == -1


class TestTransitions:
    """Tests for the TRANSITIONS dict."""

    def test_created_transitions(self):
        assert TRANSITIONS["created"] == ["recon", "failed", "paused"]

    def test_recon_transitions(self):
        assert set(TRANSITIONS["recon"]) == {"scanning", "failed", "paused"}

    def test_complete_has_no_transitions(self):
        assert TRANSITIONS["complete"] == []

    def test_failed_has_no_transitions(self):
        assert TRANSITIONS["failed"] == []

    def test_paused_can_resume(self):
        assert "recon" in TRANSITIONS["paused"]
        assert "scanning" in TRANSITIONS["paused"]
        assert "analyzing" in TRANSITIONS["paused"]

    def test_analyzing_can_loop_back(self):
        assert "recon" in TRANSITIONS["analyzing"]
        assert "scanning" in TRANSITIONS["analyzing"]

    def test_all_phases_have_transitions_defined(self):
        phase_ids = {p.id for p in PHASES}
        transition_keys = set(TRANSITIONS.keys())
        assert phase_ids == transition_keys, "Mismatch between PHASES and TRANSITIONS"

    def test_all_targets_are_valid_phases(self):
        phase_ids = {p.id for p in PHASES}
        for targets in TRANSITIONS.values():
            for target in targets:
                assert target in phase_ids, f"Invalid transition target: {target}"


class TestGetPhase:
    """Tests for get_phase function."""

    def test_get_existing_phase(self):
        phase = get_phase("scanning")
        assert phase is not None
        assert phase.id == "scanning"
        assert phase.display_name == "Scanning"

    def test_get_nonexistent_phase(self):
        assert get_phase("nonexistent") is None

    def test_get_empty_string(self):
        assert get_phase("") is None


class TestIsValidTransition:
    """Tests for is_valid_transition function."""

    def test_valid_transition(self):
        assert is_valid_transition("created", "recon") is True

    def test_invalid_transition(self):
        assert is_valid_transition("created", "complete") is False

    def test_terminal_to_anything(self):
        assert is_valid_transition("complete", "recon") is False
        assert is_valid_transition("failed", "recon") is False

    def test_loop_back_allowed(self):
        assert is_valid_transition("analyzing", "recon") is True
        assert is_valid_transition("analyzing", "scanning") is True

    def test_invalid_from_state(self):
        assert is_valid_transition("nonexistent", "recon") is False


class TestGetPhaseOrder:
    """Tests for get_phase_order function."""

    def test_known_phase(self):
        assert get_phase_order("recon") == 1
        assert get_phase_order("complete") == 5

    def test_unknown_phase_returns_sentinel(self):
        # Unknown phases return 999 so they sort at the end of progress bars,
        # not mixed with paused/failed phases that use order -1 (H8 fix).
        assert get_phase_order("nonexistent") == 999


class TestGetPhaseByStepId:
    """Tests for get_phase_by_step_id function."""

    def test_existing_step_id(self):
        phase = get_phase_by_step_id("recon")
        assert phase is not None
        assert phase.id == "recon"

    def test_vuln_mapping_step_id(self):
        phase = get_phase_by_step_id("vuln_mapping")
        assert phase is not None
        assert phase.id == "scanning"

    def test_reporting_step_id(self):
        phase = get_phase_by_step_id("reporting")
        assert phase is not None
        assert phase.id == "reporting"

    def test_nonexistent_step_id(self):
        assert get_phase_by_step_id("nonexistent") is None


class TestGetPhasesForToolPhase:
    """Tests for get_phases_for_tool_phase function."""

    def test_scan_tool_phase(self):
        phases = get_phases_for_tool_phase("scan")
        assert len(phases) > 0
        assert phases[0].id == "scanning"

    def test_recon_tool_phase(self):
        phases = get_phases_for_tool_phase("recon")
        assert len(phases) > 0
        assert phases[0].id == "recon"

    def test_unknown_tool_phase(self):
        phases = get_phases_for_tool_phase("nonexistent")
        assert phases == []


class TestToJsonSerializable:
    """Tests for to_json_serializable function."""

    def test_returns_list(self):
        result = to_json_serializable()
        assert isinstance(result, list)
        assert len(result) == len(PHASES)

    def test_has_expected_keys(self):
        result = to_json_serializable()
        for item in result:
            assert "id" in item
            assert "display_name" in item
            assert "order" in item
            assert "estimated_minutes" in item
            assert "is_terminal" in item
            assert "is_error" in item

    def test_first_phase_ordering(self):
        result = to_json_serializable()
        first = [p for p in result if p["id"] == "created"]
        assert len(first) == 1
        assert first[0]["order"] == 0
