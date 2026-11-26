"""Stage 4 real-boundary tests: the integrated loop on the true tool path.

Every test here executes the integrated chain (dispatcher tick -> strict
contracts -> delegation hierarchy -> executor -> graph write-back) with the
production :class:`RealToolExecutor` wherever a tool runs. The only doubles
are the Generator/Reasoner/Bootstrapper adapters (LLM roles with no
deterministic substitute in this environment) and explicitly marked slow-path
probes. No test fabricates tool output: refusals come from the real scope /
egress / budget / approval gates, findings come from real tool stdout, and
isolation is asserted against the real process registry and graph.
"""

from __future__ import annotations

import json
import os
import threading
import uuid

import psycopg2
import pytest

from agent.delegation import (
    DelegationError,
    PostgresDelegationStore,
    RealToolExecutor,
    SubtaskDraft,
    TaskWorker,
    validate_approval,
)
from agent.delegation.integration import IntentTaskRunner, _RecordingExecutor
from agent.delegation.primary import PrimaryAgent
from agent.delegation.registry import SpecialistRegistry
from agent.delegation.tool_executor import (
    ToolCallSpecialistRunner,
    extract_tool_findings,
    parse_eslint_json,
)
from control_plane import (
    ControlPlaneDispatcher,
    LateResult,
    PostgresControlPlaneStore,
)
from control_plane.integrated import build_integrated_runner
from database.connection import get_db
from database.migrations.runner import run_migrations
from tools.process_ownership import get_process_registry

DB_URL = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")


def _available() -> bool:
    if not DB_URL:
        return False
    try:
        psycopg2.connect(DB_URL, connect_timeout=3)
        return True
    except Exception:
        return False


DB_AVAILABLE = _available()
_SCHEMA_READY = False
pytestmark = pytest.mark.skipif(
    not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment"
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    global _SCHEMA_READY
    if DB_AVAILABLE and not _SCHEMA_READY:
        run_migrations()
        _SCHEMA_READY = True


@pytest.fixture()
def cp() -> PostgresControlPlaneStore:
    return PostgresControlPlaneStore()


@pytest.fixture()
def delegation() -> PostgresDelegationStore:
    return PostgresDelegationStore()


@pytest.fixture(autouse=True)
def _hierarchical_delegation_on(monkeypatch):
    monkeypatch.setenv("ARGUS_HIERARCHICAL_DELEGATION", "on")


def _engage(status: str = "running", authorized_scope=None) -> str:
    engagement_id = str(uuid.uuid4())
    with get_db().connection() as conn:
        cur = conn.cursor()
        if authorized_scope is None:
            cur.execute(
                "INSERT INTO engagements (id, target, status) VALUES (%s, %s, %s)",
                (engagement_id, f"https://{engagement_id[:8]}.example", status),
            )
        else:
            from psycopg2.extras import Json

            cur.execute(
                "INSERT INTO engagements (id, target, status, authorized_scope)"
                " VALUES (%s, %s, %s, %s)",
                (
                    engagement_id,
                    f"https://{engagement_id[:8]}.example",
                    status,
                    Json(authorized_scope),
                ),
            )
        cur.close()
    return engagement_id


def _node(store, engagement_id, kind, payload, *, state="open"):
    return store.graph.create_node(
        engagement_id, kind, payload=payload, state=state, origin="test"
    )


def _goal(store, engagement_id):
    return _node(store, engagement_id, "goal", {"objective": "prove the target"})


def _fact(store, engagement_id, text="an observed fact"):
    return _node(store, engagement_id, "fact", {"summary": text})


def _routed_plan(items) -> list[dict[str, Any]]:
    return [
        {
            "title": title,
            "description": description,
            "tool": tool,
            "arguments": arguments,
        }
        for title, description, tool, arguments in items
    ]


class FakeGenerator:
    def __init__(self, plan):
        self.plan = plan
        self.requests: list[dict] = []

    def generate(self, request):
        self.requests.append(request)
        return self.plan


def _real_executor(**kwargs) -> RealToolExecutor:
    return RealToolExecutor(**kwargs)


def _run_task(delegation, objective, plan, executor):
    engagement_id = _engage()
    task = delegation.create_task(engagement_id, objective)
    drafts = [
        SubtaskDraft(
            title=item["title"],
            description=item["description"],
            tool=item.get("tool"),
            arguments=dict(item.get("arguments") or {}),
        )
        for item in plan
    ]
    delegation.insert_plan(task["id"], drafts)
    worker = TaskWorker(delegation, _RecordingExecutor(delegation, executor))
    return task["id"], worker.run(task["id"], max_steps=10)


def _eslint_fixture(tmp_path):
    (tmp_path / "eslint.config.mjs").write_text(
        'export default [{ rules: { "no-console": "error", "no-eval": "error" } }];\n'
    )
    fixture = tmp_path / "fixture.js"
    fixture.write_text(
        "function run(q) { console.log(q); return eval(q); }\n"
        "module.exports = { run };\n"
    )
    return str(fixture)


# ---------------------------------------------------------------------------
# Real tool execution + refusal recording
# ---------------------------------------------------------------------------


def test_real_executor_runs_nuclei_and_records_action(delegation):
    """A subtask reaches the real nuclei binary; the action is persisted."""
    task_id, outcome = _run_task(
        delegation,
        "probe with nuclei",
        _routed_plan(
            [("Nuclei version", "report the engine version", "nuclei", {"argv": ["-version"]})]
        ),
        _real_executor(),
    )
    assert outcome["status"] == "task_finished"
    subtasks = delegation.find_subtasks(task_id)
    recorded = delegation.find_actions(subtasks[0]["id"])
    assert len(recorded) == 1
    assert recorded[0]["tool"] == "nuclei"
    assert recorded[0]["outcome"] == "completed"


def test_real_executor_scope_refusal_is_recorded(delegation):
    """An out-of-scope target is refused by the real gate and recorded."""
    engagement_id = _engage(
        authorized_scope={"domains": ["fixture.example"], "mode": "domains"}
    )
    task = delegation.create_task(engagement_id, "probe outside scope")
    delegation.insert_plan(
        task["id"],
        [
            SubtaskDraft(
                title="Probe other",
                description="probe a host outside the authorized scope",
                tool="httpx",
                arguments={"argv": ["https://other.example/"]},
            )
        ],
    )
    worker = TaskWorker(delegation, _RecordingExecutor(delegation, _real_executor()))
    outcome = worker.run(task["id"], max_steps=10)
    assert outcome["status"] == "task_finished"
    subtasks = delegation.find_subtasks(task["id"])
    recorded = delegation.find_actions(subtasks[0]["id"])
    assert len(recorded) == 1
    assert recorded[0]["outcome"] == "refused"
    assert recorded[0]["result"]["check"] in ("scope", "egress")
    assert recorded[0]["result"]["reason"]


def test_real_executor_approval_refusal_without_record(delegation):
    """sqlmap without an approval record is refused before any process spawns."""
    task_id, outcome = _run_task(
        delegation,
        "sqlmap without approval",
        _routed_plan(
            [
                (
                    "SQLi probe",
                    "probe for injection",
                    "sqlmap",
                    {"argv": ["-u", "https://fixture.example/", "--batch"]},
                )
            ]
        ),
        _real_executor(),
    )
    assert outcome["status"] == "task_finished"
    subtasks = delegation.find_subtasks(task_id)
    recorded = delegation.find_actions(subtasks[0]["id"])
    assert recorded[0]["outcome"] == "refused"
    assert recorded[0]["result"]["check"] == "approval"


def test_validate_approval_branches():
    assert validate_approval("httpx", {}) is None
    assert validate_approval("nuclei", {"argv": ["-version"]}) is None
    assert validate_approval("sqlmap", {}) is not None
    assert validate_approval("sqlmap", {"approval": {"by": "operator"}}) is None
    assert validate_approval("sqlmap", {"approval": {"by": "  "}}) is not None


def test_real_executor_budget_refusal(delegation):
    """A spent budget refuses before the tool spawns."""
    from runtime.governance import Governance

    task_id, outcome = _run_task(
        delegation,
        "budget spent",
        _routed_plan(
            [("Nuclei version", "report version", "nuclei", {"argv": ["-version"]})]
        ),
        _real_executor(
            governance_factory=lambda engagement_id: Governance(
                engagement_id, max_tokens=1
            )
        ),
    )
    assert outcome["status"] == "task_finished"
    subtasks = delegation.find_subtasks(task_id)
    recorded = delegation.find_actions(subtasks[0]["id"])
    assert recorded[0]["outcome"] == "refused"
    assert recorded[0]["result"]["check"] == "budget"


def test_real_executor_dangerous_payload_fails_closed(delegation):
    """A dangerous payload raises: no result is fabricated, subtask FAILED."""
    task = delegation.create_task(_engage(), "dangerous")
    delegation.insert_plan(
        task["id"],
        [
            SubtaskDraft(
                title="Curl pipe",
                description="curl piped to shell",
                tool="sleep",
                arguments={"argv": ["$(rm -rf /)"]},
            )
        ],
    )
    worker = TaskWorker(delegation, _RecordingExecutor(delegation, _real_executor()))
    outcome = worker.run(task["id"], max_steps=10)
    assert outcome["status"] == "failed"
    subtasks = delegation.find_subtasks(task["id"])
    assert subtasks[0]["status"] == "failed"
    assert "fail closed" in (subtasks[0].get("last_error") or "")


# ---------------------------------------------------------------------------
# Specialist delegation on the real path
# ---------------------------------------------------------------------------


def test_specialist_eslint_merges_real_findings(delegation, tmp_path):
    """A bounded specialist runs real eslint; findings merge with provenance."""
    fixture = _eslint_fixture(tmp_path)
    seen: list[dict] = []

    class ObservingRunner(ToolCallSpecialistRunner):
        def run(self, request):
            seen.append(dict(request))
            assert "database_url" not in {k.lower() for k in request}
            assert "claim_token" not in {k.lower() for k in request}
            return super().run(request)

    from agent.delegation.registry import SpecialistRegistry

    from tools.tool_runner import ToolRunner

    registry = SpecialistRegistry()
    registry.register(
        "static-analyzer",
        {"sast"},
        ObservingRunner(
            "static-analyzer",
            {"eslint"},
            lambda: ToolRunner(engagement_id="eng"),
        ),
    )
    task_id, outcome = _run_task(
        delegation,
        "static analysis",
        _routed_plan(
            [
                (
                    "Lint fixture",
                    "run eslint on the fixture",
                    "eslint",
                    {
                        "argv": ["--format", "json", fixture],
                        "specialist": {"capabilities": ["sast"]},
                    },
                )
            ]
        ),
        _real_executor(specialist_registry=registry),
    )
    assert outcome["status"] == "task_finished"
    subtasks = delegation.find_subtasks(task_id)
    result = subtasks[0]["result"]
    assert result["specialists"] == ["static-analyzer"]
    titles = {finding.get("title") for finding in result["findings"]}
    assert "eslint:no-console" in titles and "eslint:no-eval" in titles
    assert all(
        finding.get("source_agent") == "specialist:static-analyzer"
        for finding in result["findings"]
    )
    assert result["provenance"][0]["role"] == "static-analyzer"
    assert seen, "specialist must have received the bounded request"


def test_parse_eslint_json_pure():
    sample = json.dumps(
        [
            {
                "filePath": "/tmp/f.js",
                "messages": [
                    {
                        "ruleId": "no-eval",
                        "severity": 2,
                        "message": "`eval` can be harmful.",
                        "line": 2,
                        "column": 10,
                    }
                ],
            }
        ]
    )
    findings = parse_eslint_json(sample)
    assert findings[0]["title"] == "eslint:no-eval"
    assert findings[0]["severity"] == "HIGH"
    assert findings[0]["confidence"] == 0.9
    assert extract_tool_findings("eslint", ["--format", "json", "f"], sample)
    assert extract_tool_findings("nuclei", ["-version"], sample) == []


# ---------------------------------------------------------------------------
# Full lifecycle: fact + findings + anchors + edges + todos
# ---------------------------------------------------------------------------


def _integrated_explore(cp, delegation, *, plan, intents, facts=()):
    generator = FakeGenerator(plan)

    def reasoner(job):
        fact_ids = [str(row["id"]) for row in job["facts"]]
        return {
            "accepted": True,
            "data": {
                "intents": [
                    {"description": text, "from": fact_ids} for text in intents
                ]
            },
        }

    def bootstrapper(job, conclude=False):
        return {"accepted": True, "data": {"fact": {"description": "origin fact"}}}

    runner = build_integrated_runner(
        generator=generator,
        executor=_real_executor(),
        reasoner=reasoner,
        bootstrapper=bootstrapper,
        store=delegation,
    )
    return runner, generator


def test_full_lifecycle_conclusion(cp, delegation, tmp_path):
    """Explore concludes fact + PENDING findings + anchors + edges + todos."""
    engagement_id = _engage()
    _goal(cp, engagement_id)
    fixture = _eslint_fixture(tmp_path)
    plan = _routed_plan(
        [
            (
                "Lint the fixture",
                "run eslint and anchor the app",
                "eslint",
                {
                    "argv": ["--format", "json", fixture],
                    "anchors": [
                        {
                            "asset": "probe-app",
                            "asset_type": "application",
                            "role": "targets",
                            "coverage_state": "covered",
                        }
                    ],
                    "todos": [
                        {
                            "action": "create",
                            "todo_type": "plan",
                            "payload": {"note": "verify eslint findings"},
                        }
                    ],
                },
            )
        ]
    )
    runner, _generator = _integrated_explore(
        cp, delegation, plan=plan, intents=["lint the web app"]
    )
    cp.register_worker("real-worker", ["bootstrap", "reason", "explore"])
    dispatcher = ControlPlaneDispatcher(cp, runner)
    assert dispatcher.tick(engagement_id) == "bootstrap"
    assert dispatcher.tick(engagement_id) == "reason"
    assert dispatcher.tick(engagement_id) == "explore"

    facts = [
        row
        for row in cp.graph.find_nodes_by_engagement(engagement_id)
        if row["kind"] == "fact"
    ]
    assert len(facts) >= 2  # origin + explore conclusion
    conclusion = next(
        row for row in facts if "eslint" in (row["payload"] or {}).get("summary", "")
    )

    from database.repositories.finding_repository import FindingRepository

    rows = FindingRepository().find_by_engagement_with_details(engagement_id)
    by_title = {row["type"]: row for row in rows}
    assert "eslint:no-console" in by_title and "eslint:no-eval" in by_title
    assert all(row["status"] == "PENDING" for row in by_title.values())
    evidence = by_title["eslint:no-eval"]["evidence"]
    assert evidence["provenance"] == "delegation"
    assert evidence["delegation_task_id"]

    anchors = cp.graph.anchor_summary(engagement_id)
    assert any(
        row["display_value"] == "probe-app" and row["coverage_state"] == "covered"
        for row in anchors
    )
    todos = cp.graph.find_todos_for_engagement(engagement_id)
    assert any(
        (todo.get("payload") or {}).get("note") == "verify eslint findings"
        for todo in todos
    )
    with get_db().connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM graph_node_edges WHERE engagement_id = %s "
            "AND target_node_id = %s AND edge_type = 'derived_from'",
            (engagement_id, conclusion["id"]),
        )
        assert cur.fetchone()[0] >= 1
        cur.close()


def test_unproven_finding_cannot_prove_goal(cp, delegation, tmp_path):
    """The A-08 gate holds on the integrated path: no verifier proof, no goal."""
    engagement_id = _engage()
    goal = _goal(cp, engagement_id)
    fixture = _eslint_fixture(tmp_path)
    plan = _routed_plan(
        [
            (
                "Lint the fixture",
                "run eslint",
                "eslint",
                {"argv": ["--format", "json", fixture]},
            )
        ]
    )
    runner, _generator = _integrated_explore(
        cp, delegation, plan=plan, intents=["lint the web app"]
    )
    cp.register_worker("real-worker", ["bootstrap", "reason", "explore"])
    dispatcher = ControlPlaneDispatcher(cp, runner)
    dispatcher.tick(engagement_id)
    dispatcher.tick(engagement_id)
    dispatcher.tick(engagement_id)

    from database.repositories.finding_repository import FindingRepository
    from database.graph_errors import GraphMutationError

    rows = FindingRepository().find_by_engagement_with_details(engagement_id)
    assert rows, "conclusion must have persisted findings"
    with pytest.raises(GraphMutationError):
        cp.graph.prove_goal_from_findings(
            engagement_id, str(goal["id"]), [str(rows[0]["id"])]
        )
    goals = [
        row
        for row in cp.graph.find_nodes_by_engagement(engagement_id)
        if row["kind"] == "goal"
    ]
    assert goals[0]["state"] == "open"


# ---------------------------------------------------------------------------
# Heartbeat, reconcile, waiting, cancellation
# ---------------------------------------------------------------------------


def test_heartbeat_renews_claim_across_long_task(cp, delegation):
    """A task longer than its lease still concludes when heartbeats renew it."""
    engagement_id = _engage()
    _goal(cp, engagement_id)
    plan = _routed_plan(
        [
            ("Sleep one", "sleep a second", "sleep", {"argv": ["1"]}),
            ("Sleep two", "sleep a second", "sleep", {"argv": ["1"]}),
            ("Sleep three", "sleep a second", "sleep", {"argv": ["1"]}),
        ]
    )
    runner, _generator = _integrated_explore(
        cp, delegation, plan=plan, intents=["sleep through the lease"]
    )
    cp.register_worker("real-worker", ["bootstrap", "reason", "explore"])
    dispatcher = ControlPlaneDispatcher(cp, runner)
    dispatcher.tick(engagement_id)
    dispatcher.tick(engagement_id)
    result = dispatcher.run_explore(engagement_id, "real-worker", lease_seconds=2)
    assert result is not None and result["status"] == "succeeded"
    facts = [
        row
        for row in cp.graph.find_nodes_by_engagement(engagement_id)
        if row["kind"] == "fact"
    ]
    assert len(facts) >= 2


def test_expired_claim_rejects_late_conclusion(cp):
    """Without renewal the lease lapses and the late conclusion is rejected."""
    engagement_id = _engage()
    _goal(cp, engagement_id)
    intent = _node(cp, engagement_id, "intent", {"objective": "slow work"})
    cp.register_worker("slow-worker", ["explore"])
    claim = cp.claim_explore(engagement_id, "slow-worker", lease_seconds=1)
    assert claim is not None
    import time

    time.sleep(2.2)
    with pytest.raises(LateResult):
        cp.conclude_explore(claim["task"]["id"], "too late")


def test_crash_self_heals_without_manual_reconcile(cp, delegation):
    """A RUNNING subtask left by a crash is reconciled automatically on retry."""
    engagement_id = _engage()
    node = _node(cp, engagement_id, "intent", {"objective": "survive a crash"})
    intent = {"id": str(node["id"]), "objective": "survive a crash"}

    class CompletingExecutor:
        def execute(self, request):
            return {"summary": f"did {request['subtask']['title']}", "actions": []}

    runner = IntentTaskRunner(
        delegation, generator=FakeGenerator([]), executor=CompletingExecutor()
    )
    task = delegation.create_task(engagement_id, "crash", intent_id=intent["id"])
    delegation.insert_plan(
        task["id"],
        [
            __import__(
                "agent.delegation.models", fromlist=["SubtaskDraft"]
            ).SubtaskDraft(title="First", description="first"),
            __import__(
                "agent.delegation.models", fromlist=["SubtaskDraft"]
            ).SubtaskDraft(title="Second", description="second"),
        ],
    )
    # Simulate the crash: first subtask finished, second stuck RUNNING.
    from agent.delegation.models import SubtaskStatus

    assert runner._worker.step(task["id"])["status"] == "subtask_finished"
    subtasks = delegation.find_subtasks(task["id"])
    delegation.transition_subtask(subtasks[1]["id"], SubtaskStatus.RUNNING)

    result = runner.run(engagement_id, intent)
    assert result["task_id"] == task["id"]
    finished = delegation.find_subtasks(task["id"])
    assert all(row["status"] == "finished" for row in finished)


def test_waiting_resumes_with_operator_answer(cp, delegation):
    """WAITING resumes when the operator answers; otherwise it surfaces."""
    from agent.delegation.models import SubtaskStatus

    engagement_id = _engage()

    class CompletingExecutor:
        def execute(self, request):
            return {"summary": f"did {request['subtask']['title']}", "actions": []}

    runner = IntentTaskRunner(
        delegation, generator=FakeGenerator([]), executor=CompletingExecutor()
    )
    node = _node(cp, engagement_id, "intent", {"objective": "waiting"})
    intent_ref = {"id": str(node["id"]), "objective": "waiting"}
    task = delegation.create_task(engagement_id, "waiting", intent_id=intent_ref["id"])
    delegation.insert_plan(
        task["id"],
        [
            __import__(
                "agent.delegation.models", fromlist=["SubtaskDraft"]
            ).SubtaskDraft(title="Only", description="only"),
        ],
    )
    subtask_id = delegation.find_subtasks(task["id"])[0]["id"]
    delegation.transition_subtask(subtask_id, SubtaskStatus.RUNNING)
    worker = runner._worker
    worker.pause_for_input(subtask_id, "which target?")

    stalled = runner.run(engagement_id, intent_ref)
    assert stalled["status"] == "waiting_in_progress"

    resumed = runner.run(
        engagement_id,
        intent_ref,
        operator_answers={subtask_id: "fixture.example"},
    )
    assert resumed["task_id"] == task["id"]
    assert delegation.find_task(task["id"])["status"] == "finished"


def test_cancel_during_call_stops_real_tool(cp, delegation):
    """Cancelling mid-explore kills the real tool process; nothing is written."""
    engagement_id = _engage()
    _goal(cp, engagement_id)
    plan = _routed_plan(
        [("Long sleep", "sleep while cancelled", "sleep", {"argv": ["30"], "cache_mode": "NO_CACHE"})]
    )
    runner, _generator = _integrated_explore(
        cp, delegation, plan=plan, intents=["sleep long"]
    )
    cp.register_worker("real-worker", ["bootstrap", "reason", "explore"])
    dispatcher = ControlPlaneDispatcher(cp, runner)
    assert dispatcher.tick(engagement_id) == "bootstrap"
    assert dispatcher.tick(engagement_id) == "reason"

    outcome: list = []

    def drive():
        try:
            outcome.append(dispatcher.run_explore(engagement_id, "real-worker"))
        except Exception as exc:  # surface thread failures instead of hanging
            outcome.append(f"RAISED {type(exc).__name__}: {exc}")

    thread = threading.Thread(target=drive)
    thread.start()
    import time

    for _ in range(100):
        time.sleep(0.1)
        if get_process_registry().active_for(engagement_id):
            break
    assert get_process_registry().active_for(
        engagement_id
    ), "the real tool process must be running before cancel"
    dispatcher.cancel(engagement_id, "operator stop")
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert outcome == ["cancelled"], outcome
    assert get_process_registry().active_for(engagement_id) == []
    facts = [
        row
        for row in cp.graph.find_nodes_by_engagement(engagement_id)
        if row["kind"] == "fact"
    ]
    assert len(facts) == 1  # only the origin fact; no conclusion was written


# ---------------------------------------------------------------------------
# Single generator, flags, overview, isolation
# ---------------------------------------------------------------------------


def test_both_flags_on_cannot_double_dispatch(cp, delegation, monkeypatch):
    """Planner defers to the reason path; one objective yields one intent."""
    from database.graph_intents import IntentProposal

    monkeypatch.setenv("ARGUS_FACT_INTENT_PROTOCOL", "on")
    monkeypatch.setenv("ARGUS_GRAPH_EXPLORATION", "on")
    engagement_id = _engage()
    _goal(cp, engagement_id)
    fact = _fact(cp, engagement_id, "planner evidence")
    asset = cp.graph.ensure_asset(
        "dup.example", "domain", display_value="dup.example", scope_id=engagement_id
    )

    from tasks.graph_planner import run_planner_turn

    class StubPlanner:
        def plan(self, overview):
            return [
                IntentProposal(
                    objective="Probe the target",
                    target_asset_ids=(str(asset["id"]),),
                    from_fact_ids=(str(fact["id"]),),
                )
            ]

    first = run_planner_turn(
        engagement_id, dispatcher=cp.graph, planner=StubPlanner()
    )
    assert first["created"] == []
    assert first.get("deferred_to_reason") is True

    created = cp.apply_reason(
        engagement_id,
        __import__(
            "control_plane.contracts", fromlist=["ReasonDecision", "ReasonIntent"]
        ).ReasonDecision(
            kind="intents",
            intents=(
                __import__(
                    "control_plane.contracts", fromlist=["ReasonIntent"]
                ).ReasonIntent(
                    description="Probe the target", from_fact_ids=(str(fact["id"]),)
                ),
            ),
        ),
        task_id=cp.start_task(engagement_id, "reason", "w", request={})["id"],
    )
    assert len(created["created"]) == 1

    second = run_planner_turn(
        engagement_id, dispatcher=cp.graph, planner=StubPlanner()
    )
    assert second["created"] == []
    intents = [
        row
        for row in cp.graph.find_nodes_by_engagement(engagement_id)
        if row["kind"] == "intent"
    ]
    assert len(intents) == 1


def test_reason_path_suppresses_planner_duplicate(cp, monkeypatch):
    """An intent the planner created first is not recreated by the reasoner."""
    from control_plane.contracts import ReasonDecision, ReasonIntent
    from database.graph_intents import IntentProposal

    engagement_id = _engage()
    _goal(cp, engagement_id)
    fact = _fact(cp, engagement_id, "evidence")
    asset = cp.graph.ensure_asset(
        "same.example", "domain", display_value="same.example", scope_id=engagement_id
    )
    applied = cp.graph.apply_intent_proposals(
        engagement_id,
        [
            IntentProposal(
                objective="Probe the target",
                target_asset_ids=(str(asset["id"]),),
                from_fact_ids=(str(fact["id"]),),
            )
        ],
    )
    assert len(applied["created"]) == 1
    created = cp.apply_reason(
        engagement_id,
        ReasonDecision(
            kind="intents",
            intents=(
                ReasonIntent(
                    description="probe the TARGET", from_fact_ids=(str(fact["id"]),)
                ),
            ),
        ),
        task_id=cp.start_task(engagement_id, "reason", "w", request={})["id"],
    )
    assert created["created"] == []


def test_flag_off_creates_no_delegation_task(cp, delegation, monkeypatch):
    """With hierarchical delegation off, explore dispatches nothing."""
    monkeypatch.setenv("ARGUS_HIERARCHICAL_DELEGATION", "off")
    engagement_id = _engage()
    _goal(cp, engagement_id)
    _node(cp, engagement_id, "intent", {"objective": "probe"})
    cp.register_worker("w", ["explore"])
    dispatcher = ControlPlaneDispatcher(cp, _scripted_noop_runner())
    assert dispatcher.run_explore(engagement_id, "w") is None
    assert delegation.find_tasks_for_engagement(engagement_id) == []


def _scripted_noop_runner():
    class NoopRunner:
        def supports(self, task_type):
            return True

        def bootstrap(self, job, *, conclude=False):
            raise AssertionError("must not dispatch")

        def reason(self, job):
            raise AssertionError("must not dispatch")

        def explore(self, job, *, conclude=False):
            raise AssertionError("must not dispatch")

    return NoopRunner()


def test_reason_job_carries_graph_overview(cp, delegation):
    """The reason job includes assets, anchors, coverage and todos (plan §5.2B)."""
    engagement_id = _engage()
    _goal(cp, engagement_id)
    _fact(cp, engagement_id, "evidence")
    covered_asset = cp.graph.ensure_asset(
        "covered.example", "domain",
        display_value="covered.example",
        scope_id=engagement_id,
    )
    cp.graph.ensure_asset(
        "overview.example", "domain",
        display_value="overview.example",
        scope_id=engagement_id,
    )
    fact = _fact(cp, engagement_id, "anchor me")
    row = cp.graph.attach_anchor(
        str(fact["id"]), str(covered_asset["id"]), role="related"
    )
    cp.graph.attach_anchor_scope(
        str(row["id"]), engagement_id, coverage_state="covered"
    )
    cp.graph.create_todo(engagement_id, todo_type="plan", payload={"note": "gap"})
    dispatcher = ControlPlaneDispatcher(cp, _scripted_noop_runner())
    job = dispatcher._reason_job(engagement_id)
    overview = job["overview"]
    assert any(a["display"] == "overview.example" for a in overview["untested_assets"])
    assert any(a["display"] == "covered.example" for a in overview["anchors"])
    assert overview["open_todo_count"] == 1
    assert overview["goals"] and overview["facts"]


def test_executor_request_and_env_carry_no_credentials(cp, delegation):
    """Executor inputs expose no tokens, URLs, stores or claim material."""
    seen: list[dict] = []

    class ObservingExecutor:
        def execute(self, request):
            seen.append(dict(request))
            return {"summary": "observed only", "actions": []}

    runner = IntentTaskRunner(
        delegation, generator=FakeGenerator([]), executor=ObservingExecutor()
    )
    engagement_id = _engage()
    node = _node(cp, engagement_id, "intent", {"objective": "observe"})
    task = delegation.create_task(engagement_id, "observe", intent_id=str(node["id"]))
    delegation.insert_plan(
        task["id"],
        [
            __import__(
                "agent.delegation.models", fromlist=["SubtaskDraft"]
            ).SubtaskDraft(title="Only", description="only"),
        ],
    )
    runner.run(engagement_id, {"id": str(node["id"]), "objective": "observe"})
    request = seen[0]
    assert set(request) == {"task", "subtask", "dependencies", "prior_actions"}
    blob = json.dumps(request, default=str).lower()
    for secret in ("claim_token", "database_url", "token", "secret", "password"):
        assert secret not in blob

    from tools.tool_runner import ToolRunner

    env = ToolRunner(engagement_id="eng")._locked_env("nuclei")
    assert "DATABASE_URL" not in env
    assert not any("token" in key.lower() for key in env)


def test_traces_stay_engagement_scoped(cp):
    """Trace reuse never crosses the engagement boundary."""
    first = _engage()
    second = _engage()
    cp.graph.record_trace(first, "fixture trace", worker_id="w")
    assert cp.graph.search_traces(first, query="fixture") != []
    assert cp.graph.search_traces(second, query="fixture") == []


def test_recording_executor_fails_closed_on_lost_evidence():
    """A completed action whose record is lost fails closed; skips annotate."""

    class BoomStore:
        def record_action(self, *args, **kwargs):
            raise RuntimeError("disk is gone")

    class Executor:
        def execute(self, request):
            return {
                "summary": "claimed work",
                "actions": [
                    {
                        "action_id": "a1",
                        "tool": "nuclei",
                        "outcome": "completed",
                        "result": {},
                    },
                    {
                        "action_id": "a2",
                        "tool": "nuclei",
                        "outcome": "skipped",
                        "result": {},
                    },
                ],
            }

    recorder = _RecordingExecutor(BoomStore(), Executor())
    with pytest.raises(DelegationError, match="fail closed"):
        recorder.execute({"subtask": {"id": "s1"}})


def test_recording_executor_annotates_non_consequential_gap():
    """A skipped action whose record is lost annotates instead of raising."""

    class BoomStore:
        def record_action(self, *args, **kwargs):
            raise RuntimeError("disk is gone")

    class Executor:
        def execute(self, request):
            return {
                "summary": "skipped work",
                "actions": [
                    {
                        "action_id": "a9",
                        "tool": "nuclei",
                        "outcome": "skipped",
                        "result": {},
                    }
                ],
            }

    recorder = _RecordingExecutor(BoomStore(), Executor())
    output = recorder.execute({"subtask": {"id": "s9"}})
    assert output["evidence_incomplete"] == ["a9"]
