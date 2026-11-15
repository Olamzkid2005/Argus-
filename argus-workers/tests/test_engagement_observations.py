"""Tests for engagement-keyed structured observations (Stage 5.1 item 1)."""

import pytest

from agent.engagement_observations import (
    EngagementObservationStore,
    Observation,
    extract_observations,
    identity_from,
    public_identity_label,
)


@pytest.fixture
def store():
    return EngagementObservationStore()


class TestExtractObservations:
    def test_endpoint_from_discovered_url_and_parameter_from_query(self):
        observations = extract_observations(
            "eng-1",
            "nuclei",
            {"target": "https://app.example.com/search?q=test"},
            summary="scan complete",
        )
        kinds = {obs.kind: obs.value for obs in observations}
        assert kinds["endpoint"] == "https://app.example.com/search?q=test"
        assert kinds["parameter"] == "q"

    def test_endpoints_found_in_result_payload(self):
        observations = extract_observations(
            "eng-1",
            "httpx",
            {"target": "https://app.example.com"},
            result={"endpoints": ["https://app.example.com/api/users/1", "https://app.example.com/login"]},
        )
        endpoints = [obs.value for obs in observations if obs.kind == "endpoint"]
        assert "https://app.example.com/api/users/1" in endpoints
        assert "https://app.example.com/login" in endpoints

    def test_parameters_reported_by_the_tool(self):
        observations = extract_observations(
            "eng-1",
            "arjun",
            {"target": "https://app.example.com/search?q=1"},
            result={"parameters": ["q", "lang"]},
        )
        parameters = {obs.value for obs in observations if obs.kind == "parameter"}
        assert {"q", "lang"} <= parameters

    def test_auth_observation_records_identity_not_credentials(self):
        observations = extract_observations(
            "eng-1",
            "login_tool",
            {"email": "alice@example.com", "password": "hunter2"},
            success=True,
            summary="logged in",
        )
        auth = [obs for obs in observations if obs.kind == "auth"]
        assert len(auth) == 1
        assert auth[0].value == "alice@example.com"
        assert "hunter2" not in str([obs.to_dict() for obs in observations])

    def test_findings_and_failures_are_recorded(self):
        findings = extract_observations(
            "eng-1",
            "nuclei",
            {"target": "https://app.example.com"},
            result={"findings": [{"title": "Reflected XSS in /search"}]},
        )
        assert [obs.value for obs in findings if obs.kind == "finding"] == [
            "Reflected XSS in /search"
        ]

        failure = extract_observations(
            "eng-1",
            "sqlmap",
            {"target": "https://app.example.com"},
            success=False,
            summary="connection refused",
        )
        failures = [obs for obs in failure if obs.kind == "failure"]
        assert len(failures) == 1
        assert "connection refused" in failures[0].value


class TestIdentityLabels:
    def test_identity_labels_are_normalized(self):
        assert identity_from({"username": "  attacker  "}) == "attacker"
        assert public_identity_label("  attacker  ") == "attacker"
        assert public_identity_label(None) == ""

    def test_identity_labels_never_select_secret_values(self):
        assert identity_from({"username": "victim", "password": "hunter2"}) == "victim"
        assert identity_from({"password": "hunter2"}) == ""


class TestObservationStore:
    def test_records_are_keyed_by_engagement(self, store):
        store.record(
            Observation("eng-a", "endpoint", "https://a.example.com/api/1", source_tool="nuclei")
        )
        store.record(
            Observation("eng-b", "endpoint", "https://b.example.com/api/2", source_tool="nuclei")
        )
        assert store.values("eng-a", "endpoint") == ["https://a.example.com/api/1"]
        assert store.values("eng-b", "endpoint") == ["https://b.example.com/api/2"]

    def test_duplicates_are_not_recorded_twice(self, store):
        observation = Observation("eng-a", "endpoint", "https://a.example.com/api/1")
        assert store.record(observation) is True
        assert store.record(observation) is False
        assert len(store.records("eng-a")) == 1

    def test_prompt_section_groups_by_kind(self, store):
        store.record(Observation("eng-a", "endpoint", "https://a.example.com/search?q=1"))
        store.record(Observation("eng-a", "parameter", "q"))
        store.record(Observation("eng-a", "failure", "sqlmap: timeout"))
        section = store.prompt_section("eng-a")
        assert "ENDPOINT (1)" in section
        assert "https://a.example.com/search?q=1" in section
        assert "PARAMETER (1)" in section
        assert "FAILURE (1)" in section

    def test_unknown_kind_is_rejected(self, store):
        with pytest.raises(ValueError, match="Unknown observation kind"):
            store.record(Observation("eng-a", "guess", "x"))

    def test_empty_engagement_or_value_is_ignored(self, store):
        assert store.record(Observation("", "endpoint", "https://a")) is False
        assert store.record(Observation("eng-a", "endpoint", "")) is False
