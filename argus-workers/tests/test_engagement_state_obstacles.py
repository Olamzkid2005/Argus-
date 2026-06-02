"""
Unit tests for EngagementState obstacle tracking.

Covers: add_obstacle(), to_dict() count, _bump_version, from_dict
exclusion (V1 in-memory-only design), and obstacle metadata.
"""

from unittest.mock import Mock, patch

import pytest

from runtime.engagement_state import EngagementState


class TestAddObstacle:
    """Tests for EngagementState.add_obstacle()."""

    def test_sets_detected_at_if_not_provided(self):
        """add_obstacle sets detected_at if the obstacle dict doesn't have it."""
        state = EngagementState("eng-test")
        state.add_obstacle({"type": "test_obstacle", "step": "test_step"})
        assert "detected_at" in state.obstacles[0]
        assert isinstance(state.obstacles[0]["detected_at"], float)

    def test_does_not_override_existing_detected_at(self):
        """add_obstacle preserves an existing detected_at timestamp."""
        state = EngagementState("eng-test")
        fixed_time = 12345.0
        state.add_obstacle({"type": "test", "detected_at": fixed_time, "step": "test"})
        assert state.obstacles[0]["detected_at"] == fixed_time

    def test_appends_to_obstacles_list(self):
        """Multiple obstacles are appended, not overwritten."""
        state = EngagementState("eng-test")
        state.add_obstacle({"type": "obs_a", "step": "s1"})
        state.add_obstacle({"type": "obs_b", "step": "s2"})
        assert len(state.obstacles) == 2
        assert state.obstacles[0]["type"] == "obs_a"
        assert state.obstacles[1]["type"] == "obs_b"

    def test_triggers_bump_version(self):
        """add_obstacle calls _bump_version, incrementing state_version."""
        state = EngagementState("eng-test")
        v0 = state.state_version
        state.add_obstacle({"type": "test", "step": "test"})
        assert state.state_version == v0 + 1

    def test_persists_full_obstacle_dict(self):
        """The full obstacle dict is stored (not a truncated version)."""
        state = EngagementState("eng-test")
        obstacle = {
            "type": "auth_failed_a",
            "step": "authenticate",
            "recoverable": False,
            "recovery_paths": ["skip"],
            "metadata": {"role": "user_a", "error_class": "AuthError"},
        }
        state.add_obstacle(obstacle)
        stored = state.obstacles[0]
        assert stored["type"] == "auth_failed_a"
        assert stored["step"] == "authenticate"
        assert stored["metadata"]["error_class"] == "AuthError"

    def test_standard_fields_stored_correctly(self):
        """Standard obstacle fields match the contract from the plan."""
        state = EngagementState("eng-test")
        state.add_obstacle({
            "type": "target_unreachable",
            "step": "discover_resources",
            "recoverable": False,
            "recovery_paths": ["skip"],
            "metadata": {"target": "http://example.com", "probed_endpoints": 5},
        })
        o = state.obstacles[0]
        assert o["type"] == "target_unreachable"
        assert o["recoverable"] is False
        assert o["recovery_paths"] == ["skip"]
        assert o["metadata"]["target"] == "http://example.com"


class TestObstaclesCount:
    """Tests for obstacles_count in to_dict()."""

    def test_obstacles_count_zero_initially(self):
        """to_dict includes obstacles_count=0 when no obstacles added."""
        state = EngagementState("eng-test")
        d = state.to_dict()
        assert d["obstacles_count"] == 0

    def test_obstacles_count_reflects_added_obstacles(self):
        """obstacles_count increments correctly."""
        state = EngagementState("eng-test")
        state.add_obstacle({"type": "a", "step": "1"})
        assert state.to_dict()["obstacles_count"] == 1
        state.add_obstacle({"type": "b", "step": "2"})
        assert state.to_dict()["obstacles_count"] == 2

    def test_obstacles_count_visible_in_redis_snapshot(self):
        """obstacles_count is part of the to_dict() Redis cache payload."""
        state = EngagementState("eng-test")
        state.add_obstacle({"type": "a", "step": "1"})
        d = state.to_dict()
        # to_dict is what _bump_version sends to Redis
        assert "obstacles_count" in d
        assert d["obstacles_count"] == 1

    def test_obstacles_not_included_in_to_dict(self):
        """Full obstacles list is NOT in to_dict (count-only summary)."""
        state = EngagementState("eng-test")
        state.add_obstacle({"type": "secret", "step": "test"})
        d = state.to_dict()
        assert "obstacles" not in d  # only the count


class TestObstaclesRoundtrip:
    """Tests that obstacles follow the V1 in-memory-only design."""

    def test_from_dict_does_not_restore_obstacles(self):
        """from_dict does NOT restore obstacles (in-memory only in V1)."""
        state = EngagementState("eng-test")
        state.add_obstacle({"type": "test", "step": "test"})
        # Serialize via to_dict (counts only) then reconstruct
        d = state.to_dict()
        restored = EngagementState.from_dict(d)
        assert len(restored.obstacles) == 0  # obstacles not persisted

    def test_snapshot_dict_does_not_include_obstacles(self):
        """to_snapshot_dict does not include obstacles (V1 design)."""
        state = EngagementState("eng-test")
        state.add_obstacle({"type": "test", "step": "test"})
        snap = state.to_snapshot_dict()
        assert "obstacles" not in snap
