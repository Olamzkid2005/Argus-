"""Tests for the Stage 7.2 harness opt-in and specialist verdicts.

Both are pure functions so they can be proven without PostgreSQL, Redis, a
worker or scanner binaries. The point is that bad options fail before dispatch
and that "Swarm: no specialists activated" can never produce a passing verdict.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

LIVEFIRE = Path(__file__).resolve().parents[2] / "scripts" / "livefire"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LIVEFIRE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


config = _load("harness_config", "harness_config.py")
assertions = _load("assert_livefire", "assert-livefire.py")


def opts(**env):
    return config.resolve_options({key: str(value) for key, value in env.items()})


class TestHarnessOptions:
    def test_defaults_are_moderate_and_do_not_require_swarm(self):
        options = opts()
        assert options.aggressiveness == "moderate"
        assert options.scan_mode == "standard"
        assert options.require_swarm is False
        assert options.required_specialists == ()

    def test_elevated_scanning_must_be_explicit(self):
        options = opts(AGGRESSIVENESS="high", SCAN_MODE="swarm")
        assert options.aggressiveness == "high"
        assert options.required_specialists == ()

    def test_malformed_aggressiveness_fails(self):
        with pytest.raises(config.ConfigError):
            opts(AGGRESSIVENESS="turbo")

    def test_malformed_scan_mode_fails(self):
        with pytest.raises(config.ConfigError):
            opts(SCAN_MODE="stealth")

    def test_malformed_boolean_fails(self):
        with pytest.raises(config.ConfigError):
            opts(REQUIRE_SWARM="maybe")

    def test_require_swarm_needs_an_elevated_aggressiveness(self):
        with pytest.raises(config.ConfigError, match="AGGRESSIVENESS=high"):
            opts(REQUIRE_SWARM="1")

    def test_require_swarm_rejects_the_deterministic_route(self):
        with pytest.raises(config.ConfigError, match="deterministic"):
            opts(REQUIRE_SWARM="1", AGGRESSIVENESS="high", SCAN_MODE="deterministic")

    def test_require_swarm_defaults_to_all_three_specialists(self):
        options = opts(REQUIRE_SWARM="1", AGGRESSIVENESS="high")
        assert options.require_swarm is True
        assert set(options.required_specialists) == {"idor", "auth", "api"}

    def test_required_specialists_must_be_known_and_unique(self):
        with pytest.raises(config.ConfigError, match="unknown"):
            opts(REQUIRE_SWARM="1", AGGRESSIVENESS="high", REQUIRED_SPECIALISTS="idor,csrf")
        with pytest.raises(config.ConfigError, match="repeats"):
            opts(REQUIRE_SWARM="1", AGGRESSIVENESS="high", REQUIRED_SPECIALISTS="idor,idor")

    def test_required_specialists_without_require_swarm_fails(self):
        with pytest.raises(config.ConfigError, match="REQUIRE_SWARM=1"):
            opts(REQUIRED_SPECIALISTS="idor")

    def test_effective_config_saves_payload_scope_ids_and_feature_flags(self):
        options = opts(REQUIRE_SWARM="1", AGGRESSIVENESS="high")
        saved = config.effective_config(
            options,
            target_url="http://127.0.0.1:8080",
            engagement_id="ENG-1",
            scope={"mode": "allowlist", "allowed_targets": ["http://127.0.0.1:8080"]},
            env={"ARGUS_FF_SWARM_SPECIALISTS": "1", "IGNORED": "x"},
        )
        assert saved["options"]["require_swarm"] is True
        assert saved["target_url"] == "http://127.0.0.1:8080"
        assert saved["engagement_id"] == "ENG-1"
        assert saved["scope"]["mode"] == "allowlist"
        assert saved["feature_flags"] == {"ARGUS_FF_SWARM_SPECIALISTS": "1"}


def _event(domain: str, event: str, **fields) -> dict:
    return {"engagement_id": "ENG-1", "domain": domain, "event": event, **fields}


def _good_events(domain: str) -> list[dict]:
    return [
        _event(domain, "agent_started"),
        _event(domain, "tool_selected", tool="nuclei"),
        _event(domain, "tool_executed", tool="nuclei", status="success", findings=1),
        _event(domain, "agent_completed", status="completed", findings_count=1),
    ]


def _by_name(criteria: list[dict]) -> dict[str, dict]:
    return {item["name"]: item for item in criteria}


class TestSwarmCriteria:
    def test_parses_only_this_engagements_structured_events(self):
        lines = [
            '[INFO] [SWARM_EVENT] {"engagement_id": "ENG-1", "domain": "idor", "event": "agent_started"}',
            '[INFO] [SWARM_EVENT] {"engagement_id": "ENG-2", "domain": "idor", "event": "agent_started"}',
            "[INFO] [SWARM_EVENT] not-json",
            "Swarm: no specialists activated",
        ]
        events = assertions.parse_swarm_events(lines, "ENG-1")
        assert len(events) == 1
        assert events[0]["domain"] == "idor"

    def test_a_complete_specialist_passes_every_criterion(self):
        criteria, summary = assertions.swarm_criteria(
            _good_events("idor"), ["idor"]
        )
        checks = _by_name(criteria)
        assert checks["swarm_idor_activated"]["passed"] is True
        assert checks["swarm_idor_tool_executed"]["passed"] is True
        assert checks["swarm_idor_completed"]["passed"] is True
        assert checks["swarm_idor_provenance"]["passed"] is True
        assert checks["swarm_idor_no_failures"]["passed"] is True
        assert summary["idor"]["executed_tools"] == ["nuclei"]

    def test_no_specialists_activated_fails(self):
        criteria, _ = assertions.swarm_criteria(
            [_event("swarm", "no_specialists_activated")], ["idor", "auth", "api"]
        )
        checks = _by_name(criteria)
        assert checks["swarm_specialists_activated"]["passed"] is False
        assert checks["swarm_idor_activated"]["passed"] is False

    def test_activation_without_execution_or_completion_fails(self):
        criteria, _ = assertions.swarm_criteria(
            [_event("auth", "agent_started")], ["auth"]
        )
        checks = _by_name(criteria)
        assert checks["swarm_auth_activated"]["passed"] is True
        assert checks["swarm_auth_tool_executed"]["passed"] is False
        assert checks["swarm_auth_completed"]["passed"] is False

    def test_completed_with_errors_is_not_successful_completion(self):
        events = _good_events("api")
        events[-1] = _event("api", "agent_completed", status="error")
        criteria, _ = assertions.swarm_criteria(events, ["api"])
        checks = _by_name(criteria)
        assert checks["swarm_api_completed"]["passed"] is False
        assert checks["swarm_api_no_failures"]["passed"] is False

    def test_failed_tool_execution_fails(self):
        events = _good_events("idor")
        events[2] = _event("idor", "tool_executed", tool="nuclei", status="failed")
        criteria, _ = assertions.swarm_criteria(events, ["idor"])
        checks = _by_name(criteria)
        assert checks["swarm_idor_tool_executed"]["passed"] is False
        assert checks["swarm_idor_no_failures"]["passed"] is False

    def test_selection_without_matching_execution_fails_provenance(self):
        events = _good_events("idor")
        events[1] = _event("idor", "tool_selected", tool="nuclei")
        events[2] = _event("idor", "tool_executed", tool="sqlmap", status="success")
        criteria, _ = assertions.swarm_criteria(events, ["idor"])
        checks = _by_name(criteria)
        assert checks["swarm_idor_provenance"]["passed"] is False
