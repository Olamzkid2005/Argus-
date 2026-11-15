"""Unit tests for AgentSessionStore."""

import pytest

from agent.session_store import AgentSession, AgentSessionStore, ToolExecution


@pytest.fixture
def store():
    return AgentSessionStore()


@pytest.fixture
def session_id(store):
    return store.create(target="https://example.com", phase="recon")


class TestCreate:
    def test_creates_session(self, store):
        sid = store.create(target="https://example.com", phase="recon")
        session = store.get(sid)
        assert session.target == "https://example.com"
        assert session.phase == "recon"
        assert session.tech_stack == []
        assert session.current_plan is None
        assert session.plan_step == 0

    def test_creates_with_tech_stack(self, store):
        sid = store.create(
            target="https://example.com", phase="scan", tech_stack=["python", "flask"]
        )
        session = store.get(sid)
        assert session.tech_stack == ["python", "flask"]

    def test_unique_session_ids(self, store):
        s1 = store.create(target="a", phase="p1")
        s2 = store.create(target="b", phase="p2")
        assert s1 != s2


class TestGet:
    def test_returns_session(self, store, session_id):
        session = store.get(session_id)
        assert isinstance(session, AgentSession)

    def test_raises_on_missing(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.get("nonexistent")


class TestAddExecution:
    def test_adds_execution(self, store, session_id):
        exec = ToolExecution(
            tool="nuclei",
            arguments={"target": "x"},
            reasoning="test",
            success=True,
            duration_ms=100,
            finding_count=1,
            summary="ok",
        )
        store.add_execution(session_id, exec)
        session = store.get(session_id)
        assert len(session.tool_history) == 1
        assert session.tool_history[0].tool == "nuclei"

    def test_raises_on_missing_session(self, store):
        exec = ToolExecution(
            tool="nuclei",
            arguments={},
            reasoning="",
            success=True,
            duration_ms=0,
            finding_count=0,
            summary="",
        )
        with pytest.raises(ValueError, match="not found"):
            store.add_execution("nonexistent", exec)


class TestAddObservation:
    def test_adds_observation(self, store, session_id):
        store.add_observation(session_id, "found something")
        session = store.get(session_id)
        assert "found something" in session.observations

    def test_raises_on_missing_session(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.add_observation("nonexistent", "test")


class TestSetPlan:
    def test_sets_plan_and_resets_step(self, store, session_id):
        store.set_plan(session_id, ["nuclei", "nmap"])
        session = store.get(session_id)
        assert session.current_plan == ["nuclei", "nmap"]
        assert session.plan_step == 0

    def test_raises_on_missing_session(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.set_plan("nonexistent", ["nuclei"])


class TestAdvancePlan:
    def test_normal_case(self, store, session_id):
        store.set_plan(session_id, ["nuclei", "nmap"])
        assert store.advance_plan(session_id) == "nuclei"
        assert store.advance_plan(session_id) == "nmap"

    def test_exhausted(self, store, session_id):
        store.set_plan(session_id, ["nuclei"])
        store.advance_plan(session_id)
        assert store.advance_plan(session_id) is None

    def test_no_plan(self, store, session_id):
        assert store.advance_plan(session_id) is None

    def test_raises_on_missing_session(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.advance_plan("nonexistent")


class TestAddFinding:
    def test_adds_finding(self, store, session_id):
        finding = {"title": "SQLi", "severity": 4}
        store.add_finding(session_id, finding)
        session = store.get(session_id)
        assert len(session.findings) == 1
        assert session.findings[0]["title"] == "SQLi"

    def test_raises_on_missing_session(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.add_finding("nonexistent", {"title": "test"})


class TestStage5PlanArguments:
    """Stage 5.1 item 2: plan entries keep their arguments."""

    def test_advance_plan_entry_returns_arguments_with_the_tool(self, store, session_id):
        store.set_plan(
            session_id,
            ["nuclei", "nmap"],
            sources=["llm", "llm"],
            argument_map=[{"severity": "high"}, {}],
        )
        assert store.advance_plan_entry(session_id) == ("nuclei", "llm", {"severity": "high"})
        assert store.advance_plan_entry(session_id) == ("nmap", "llm", {})
        assert store.advance_plan_entry(session_id) is None

    def test_names_only_plan_yields_empty_arguments(self, store, session_id):
        store.set_plan(session_id, ["nuclei"])
        assert store.advance_plan_entry(session_id) == ("nuclei", "deterministic", {})

    def test_partial_argument_map_is_padded(self, store, session_id):
        store.set_plan(session_id, ["nuclei", "nmap"], argument_map=[{"severity": "high"}])
        store.advance_plan_entry(session_id)
        assert store.advance_plan_entry(session_id) == ("nmap", "deterministic", {})


class TestStage5SessionPolicyState:
    """Stage 5.1 item 3 + Stage 5.2 item 6 session state."""

    def test_action_signatures_and_counts_are_tracked(self, store, session_id):
        store.record_action_signature(session_id, "nuclei", "sig-a")
        store.record_action_signature(session_id, "nuclei", "sig-b")
        assert store.action_signatures(session_id) == {"sig-a": "nuclei", "sig-b": "nuclei"}
        assert store.action_counts(session_id) == {"nuclei": 2}

    def test_executed_tools_and_coverage_are_recorded(self, store, session_id):
        store.record_executed_tool(session_id, "nuclei")
        store.record_executed_tool(session_id, "nuclei")
        store.set_required_coverage(session_id, ["nuclei", "nmap"])
        store.set_stop_requested(session_id)
        session = store.get(session_id)
        assert session.executed_tools == ["nuclei"]
        assert session.required_coverage == ["nuclei", "nmap"]
        assert session.stop_requested is True

    def test_structured_observations_are_deduplicated(self, store, session_id):
        first = store.add_structured_observations(
            session_id,
            [
                {"kind": "endpoint", "value": "https://example.com/a"},
                {"kind": "endpoint", "value": "https://example.com/a"},
            ],
        )
        second = store.add_structured_observations(
            session_id, [{"kind": "endpoint", "value": "https://example.com/a"}]
        )
        assert first == 1
        assert second == 0
        assert store.get(session_id).structured_observations == [
            {"kind": "endpoint", "value": "https://example.com/a"}
        ]
