# PentAGI conformance ledger — hierarchical delegation (P-01…P-17)

**Date:** 25 November 2026
**Plan:** `docs/conformance/argus_three_frameworks_implementation_conformance_plan.md` §4, §4.11
**Reference pin:** PentAGI `cffed9485aa1cca70762cd08a57ac62a80406258`
**Argus baseline for this pass:** `896fb764` plus the changes listed under *Implementation surfaces*
**Authoritative backend:** PostgreSQL via `argus-workers/database` (see `authoritative-state-backend-note.md`)

Statuses follow the plan §7.3 rules: `PASS` needs a code path **and** a test that ran in this
checkout, plus runtime evidence for state-machine behaviour.

---

## 1. Verification commands and observed results

Run on 25 November 2026 against a local PostgreSQL **16.2** instance (pgserver), with the
migration runner applied through `039_delegation_completion_condition.sql`.

| Command | Result |
|---|---|
| `cd argus-workers && python -m pytest tests/test_pentagi_delegation.py -q -p no:randomly` | **45 passed** |
| `cd argus-workers && python -m pytest tests/test_pentagi_delegation.py tests/test_graph_planner.py -q -p no:randomly` | **passed** (no planner regression; see §6) |
| `cd argus-workers && ruff check .` | clean |
| `cd argus-workers && python scripts/check_graph_import_boundary.py` | clean (C-18 boundary) |
| `git diff --check` | clean |

The suite is DB-backed and skipped when `DATABASE_URL` is unreachable, exactly like the
graph tests. The counts above are from a run with a reachable database, not from a
collection-only pass.

---

## 2. Implementation surfaces

```text
argus-workers/agent/delegation/
  __init__.py            public contract exports
  models.py              Task/Subtask/Action status contract + transitions + 15 cap
  generator.py           ordered plan validation, dedupe, deterministic topo order
  patch.py               ADD/REMOVE/MODIFY/REORDER validation and application
  refiner.py             bounded refiner request + atomic patch persistence
  reflector.py           parse → repair loop capped at 3 attempts
  primary.py             Primary Agent, bounded specialist payload, conflict routing
  registry.py            specialist roles and capability lookup
  reporter.py            one report from persisted results/evidence
  memorist.py            redaction + tenant-scoped recall
  worker.py              sequential TaskWorker, WAITING, restart reconciliation
  store.py               PostgreSQL persistence for the whole hierarchy
argus-workers/database/migrations/038_delegation_hierarchy.sql
argus-workers/database/migrations/039_delegation_completion_condition.sql
argus-workers/tests/test_pentagi_delegation.py
```

`argus-workers/orchestrator_pkg/planning/flags.py` now exposes
`hierarchical_delegation_mode()` for `ARGUS_HIERARCHICAL_DELEGATION`, which previously had
only the environment name in the flag table.

Design boundaries:

- Agents return structured output. Only `PostgresDelegationStore` writes task state, and
  `PrimaryAgent` holds no store reference, so a specialist cannot mutate the task or graph.
- The engagement is the Flow; a Task carries the graph investigation intent
  (`delegation_tasks.intent_id`, ownership checked against `graph_nodes.engagement_id`).
- Subtask order is an explicit `ordinal`; a unique `(task_id, ordinal)` constraint plus a
  per-task row lock serialize plan writes.
- Completed subtask rows are immutable through the refiner path: patch validation only
  accepts planned (`created`) subtasks for REMOVE/MODIFY/REORDER.

---

## 3. Requirement ledger

Upstream references are the pinned PentAGI files cited by plan §1/§4. The pinned source is
**not vendored in this checkout**, so symbols below are named from the plan's behaviour
statements rather than re-read here; that limitation is recorded in §6.

| ID | Reference behaviour | Upstream proof (pinned path) | Argus implementation | Test proof | Runtime proof | Result | Deviation |
|---|---|---|---|---|---|---|---|
| P-01 | Engagement → Task → Subtask → Action hierarchy with correct FK ownership | `backend/pkg/controller/task.go`, `backend/pkg/controller/subtask.go`, `backend/docs/flow_execution.md` | `agent/delegation/models.py` (`Task`, `Subtask`, `Action`), `agent/delegation/store.py` (`create_task`, `insert_plan`, `record_action`), `database/migrations/038_delegation_hierarchy.sql` | `TestP01Hierarchy::test_engagement_task_subtask_action_ownership`, `::test_status_transitions_are_monotonic` | PostgreSQL 16.2 run; cross-engagement intent rejected before insert; action FK returns to its subtask | PASS | Task is `delegation_tasks` in the Argus repository, not a second Flow table: Argus Engagement is the Flow (plan §4.2) |
| P-02 | Generator returns 16 subtasks → explicit policy, never more than 15 persisted | `backend/docs/flow_execution.md` (15-subtask generator cap) | `agent/delegation/generator.py:validate_generated_plan` (`over_limit="reject"` default, `"clamp"` option), `store.insert_plan` guard | `TestP02GeneratorCap::test_sixteen_subtasks_are_rejected_or_clamped` | 16 → rejected; clamp → 15 rows, ordinals 1…15 | PASS | Two explicit policies instead of one; default reject, clamp opt-in. Clamping is refused when a kept subtask depends on a clamped-away draft |
| P-03 | Generator returns unordered dependencies → dispatcher validates and stores one deterministic valid order; violations rejected | `backend/pkg/controller/task.go` (ordered subtask generation), `backend/pkg/providers/subtask_patch.go` | `generator.py:_topological_order`, `_resolve_reference`, `store._resolve_dependencies` | `TestP03DependencyOrder::test_unordered_dependencies_are_stored_in_valid_order`, `::test_dependency_violations_are_rejected` | Stored order `first, second, third`; `depends_on` holds persisted IDs; cycle/missing name rejected | PASS | Integer references are 1-based positions in the generator output; string references are titles |
| P-04 | Three-subtask task: 2 does not start before 1 terminal; 3 before 2 | `backend/docs/flow_execution.md` (sequential subtasks) | `store.claim_next_subtask` (first active row only, dependency clause), `worker.py` | `TestP04SequentialExecution::test_subtasks_start_in_order_only_after_predecessor_is_terminal` | Second claim while RUNNING returns `running_in_progress`; each next step needs the prior FINISHED | PASS | none |
| P-05 | Two independent intent tasks may run concurrently; each remains sequential | `backend/pkg/controller/task.go` | `store.create_task` per intent; per-task `FOR UPDATE` in `claim_next_subtask` | `TestP05ConcurrentTasks::test_two_tasks_run_concurrently_but_each_is_sequential` | Both tasks RUNNING at once; task A's second step stays blocked while its first runs | PASS | Concurrency is bounded by the graph frontier/worker limits, not by this module |
| P-06 | Complete a subtask → Refiner invoked with completed result, remaining tasks, graph/facts | `backend/pkg/controller/task.go`, `backend/docs/flow_execution.md` | `refiner.py:build_request`, `RefinerService.refine_after`; `worker.py:_after_terminal` | `TestP06RefinerInvocation::test_refiner_gets_completed_result_remaining_plan_and_facts` | Recorded request contained completed result, remaining `Second/Third`, facts and graph changes | PASS | Facts/graph changes are passed by the caller (worker passes the subtask result's `facts`); no live graph query in this module |
| P-07 | ADD/REMOVE/MODIFY/REORDER match reference delta semantics and insertion ordering | `backend/pkg/providers/subtask_patch.go` (patch operations) | `patch.py:apply_patch`, `store.apply_plan` | `TestP07PatchTypes::test_add_remove_modify_reorder_match_delta_semantics` | Applied order `zero, one, four, between, three updated`; patch row records all five operations | PASS | `at_beginning` is the explicit beginning marker; `after_id` is the only insertion point |
| P-08 | Patch references unknown ID → whole patch rejected, no partial corruption | `backend/pkg/providers/subtask_patch.go` | `patch.py:_find`/`apply_patch`, `refiner.py`, `store.apply_plan` transaction | `TestP08UnknownReference::test_unknown_id_rejects_patch_without_partial_corruption` | Valid ADD plus unknown REMOVE: patch rejected, plan and patch ledger unchanged | PASS | Policy is reject-all; no normalisation fallback |
| P-09 | Refiner edits completed evidence → rejected; result/history immutable | `backend/pkg/providers/subtask_patch.go`, `backend/pkg/controller/subtask.go` | `patch.py` editable-status rule (`created` only) | `TestP09CompletedEvidence::test_refiner_cannot_edit_a_completed_subtask` | MODIFY of FINISHED subtask rejected; title/result unchanged; no patch row | PASS | none |
| P-10 | Patch creates 16 active subtasks → rejected; persisted plan unchanged | `backend/pkg/providers/subtask_patch.go` (15 cap) | `patch.py:_check_active`, `store.apply_plan` cap guard | `TestP10ActiveCap::test_patch_over_the_active_cap_is_rejected` | 15 planned + ADD rejected; 15 rows and no patch row remain | PASS | "Active" means non-terminal (`created/running/waiting`) |
| P-11 | Primary Agent delegates to specialist with bounded context; provenance returns; no direct DB mutation | `backend/docs/flow_execution.md` (primary/specialist delegation) | `primary.py:PrimaryAgent.handle`, `SpecialistRequest.as_payload`; `registry.py` | `TestP11SpecialistDelegation::test_specialist_gets_bounded_context_and_returns_provenance`, `::test_conflicting_specialist_findings_go_to_verification` | Payload truncated to 3 facts / 2 targets / 2 tools; subtask/action counts unchanged; conflicts marked `requires_verification` | PASS | Specialist runner is a typed adapter; live specialist implementations are injected by the caller (not launched here) |
| P-12 | Invalid/unstructured output → at most 3 Reflector attempts; failure explicit, not completion | `backend/docs/flow_execution.md` (3 correction attempts), `backend/pkg/controller/subtask.go` | `reflector.py:Reflector.parse_or_repair`, `worker.py` failure path | `TestP12ReflectionLimit::test_reflector_stops_after_three_attempts`, `::test_invalid_output_marks_the_subtask_failed_not_finished` | Repair called exactly 3 times; subtask FAILED with explicit error; task not FINISHED; `finalize_task` raises | PASS | `attempts` counts repair calls (max 3); the initial parse is not an attempt |
| P-13 | Agent requests operator input → subtask WAITING; input resumes same task/context | `backend/pkg/controller/subtask.go` (`ask`/waiting) | `worker.py:pause_for_input`, `resume_subtask`; `store.transition_subtask` | `TestP13Waiting::test_waiting_subtask_resumes_same_task_and_chain`, `TestReviewHardening::test_question_and_answer_survive_resume` | WAITING blocks other subtasks; resume returns RUNNING on the same task and message chain | PASS | The question and operator input are merged into the subtask result history rather than replacing one another |
| P-14 | Process dies while RUNNING → restart reconciles resumable state, evidence remains, no blind replay | `backend/docs/flow_execution.md` (reload running subtask as created) | `store.reconcile_stale_subtasks`, `worker.reconcile`, `worker.step` (`prior_actions`) | `TestP14RestartRecovery::test_interrupted_subtask_becomes_resumable_and_reuses_actions` | Reconciled to `created`, message chain preserved, action ledger unchanged, resumed executor received the prior action | PASS | The action ledger is exposed to the executor, which decides reuse; this module does not re-execute tools |
| P-15 | All required subtasks finish → Reporter runs once from persisted findings/evidence | `backend/docs/flow_execution.md` (reporter), `backend/docs/flow_execution.md` (memorist/report roles) | `reporter.py:Reporter.report`, `store.save_report` (`ON CONFLICT (task_id) DO NOTHING`) | `TestP15Reporter::test_reporter_uses_persisted_state_and_runs_once` | First report has 2 persisted findings and both evidence refs; late action does not change the report; second call `created: false` | PASS | `unresolved` required subtasks block finalization before the Reporter is reached |
| P-16 | Memorist retrieves prior engagement knowledge; only permitted tenant-scoped, redacted context | `backend/docs/flow_execution.md` (memorist) | `memorist.py:redact_secrets`, `Memorist.remember/recall`, `store.search_memory` | `TestP16Memorist::test_memorist_redacts_and_enforces_tenant_boundary` | Password/API key redacted; tenant B and no-tenant engagement receive `[]`; tenant A sees its one memory | PASS | `tenant_id` is `engagements.org_id`; an engagement with no org fails closed |
| P-17 | Failed/blocked/skipped subtask → task cannot be fully successful without explicit resolution | `backend/pkg/controller/task.go` (task completion), `backend/docs/flow_execution.md` | `store.finalize_task`, `store.resolve_subtask` | `TestP17Resolution::test_failed_subtask_needs_an_explicit_resolution`, `::test_skipped_subtask_without_resolution_blocks_completion`, `TestReviewHardening::test_resolved_skip_or_failure_unblocks_dependents` | Finalize raises `TaskCompletionError`; after resolution it finishes and the report records the reason | PASS | Resolution is a free-text reason on the subtask; it is recorded, not inferred. A resolved terminal failure/skip satisfies a dependency so dependents cannot deadlock the task |

### 3a. Fresh-review corrections

A second read of the eleven modules found contracts that were too permissive or
silently lossy. Each is now a regression test in the same file:

| Finding | Fix | Tests |
|---|---|---|
| Replaying a terminal transition could overwrite a completed result | transitions cannot re-enter a state; FINISHED requires a persisted result; FAILED/SKIPPED/CANCELLED require an explicit reason | `TestReviewHardening::test_repeated_terminal_transition_cannot_rewrite_result`, `::test_finish_requires_a_persisted_result`, `::test_failure_requires_an_explicit_reason` |
| `apply_plan` could update another task's subtask by ID | every existing item must belong to the target task; updates and deletes are scoped by `task_id` | `::test_apply_plan_rejects_another_tasks_subtask` |
| The 15 cap counted total history, rejecting a legitimate long task | the cap counts active (non-terminal) subtasks only; completed history may exceed 15 | `::test_refiner_can_grow_completed_history_past_fifteen` |
| A new item carrying a terminal status bypassed the active cap | new rows always count as active because they are inserted as `created` | `::test_new_item_cannot_bypass_the_active_cap_with_a_terminal_status` |
| Running subtasks could be edited through the direct store path | every non-`created` subtask keeps its title, description, status, completion condition and dependencies | `::test_apply_plan_rejects_editing_a_running_subtask`, `::test_apply_plan_rejects_rewriting_completed_evidence` |
| A finished task could receive new work | `apply_plan` and `insert_plan` reject finished/failed tasks | `::test_finished_task_plan_is_immutable` |
| A resolved skip left dependents blocked forever | a resolved failed/skipped/cancelled dependency satisfies the dependency | `::test_resolved_skip_or_failure_unblocks_dependents` |
| Clamping silently dropped a prerequisite | a dependency on a clamped-away draft rejects the plan instead of dropping the edge | `::test_generator_clamp_rejects_dependency_on_a_clamped_draft` |
| Patch validation deferred dependency errors to the store | ADD/REMOVE validate every dependency against the working plan before persistence | `::test_patch_add_with_unknown_dependency_is_rejected`, `::test_patch_rejects_removing_a_prerequisite` |
| A repeated `run` raised after the task was finished | `finalize_task` is idempotent and returns the finished task | `::test_repeated_run_is_idempotent` |
| Executor/repair-agent exceptions left a subtask RUNNING | worker records an explicit FAILED with the error and invokes the Refiner | `::test_worker_records_an_executor_failure_as_failed` |
| `completion_condition` was generated then silently dropped | migration `039` adds the column; insert, patch persistence and `plan_items` carry it | `::test_completion_condition_is_persisted` |
| Unscoped memory could be written but never read | Memorist/store refuse an engagement without a tenant; tenant mismatch is rejected | `::test_memorist_rejects_an_unscoped_engagement` |
| Malformed specialist findings raised a generic `ValueError` | findings must be objects; a non-object rejects the delegation with `DelegationError` | `::test_primary_rejects_non_object_specialist_findings` |


---

## 4. State-machine evidence

| Transition | Enforced by | Evidence |
|---|---|---|
| `CREATED → RUNNING` | `store.claim_next_subtask` (`UPDATE … WHERE status='created'`) | P-04/P-05 |
| `RUNNING → WAITING` | `validate_subtask_transition`, `worker.pause_for_input` | P-13 |
| `WAITING → RUNNING` | `validate_subtask_transition`, `worker.resume_subtask` | P-13 |
| `RUNNING → FINISHED` | `validate_subtask_transition`, `worker.step` | P-04/P-15 |
| `RUNNING → FAILED` | `worker.step` after `ReflectionExhausted` | P-12 |
| terminal → anything | rejected by the empty transition set | P-01 |
| Task `WAITING → FINISHED` | only through `finalize_task` after every required subtask is resolved | P-17 |

Reconciliation (`RUNNING → CREATED`) is deliberately outside the normal transition table:
it is the restart path, records `last_error='interrupted: reconciled to resumable'`, and
keeps result, message chain and action rows (P-14).

---

## 5. Implementation decisions and adaptations

1. **One hierarchy, not two.** Engagement = Flow; `delegation_tasks.intent_id` points at the
   graph intent node. There is no separate `Flow` table, matching plan §4.2.
2. **Durable state in PostgreSQL.** The store lives next to the existing engagement
   repository; the ephemeral `AgentSessionStore` is untouched. Migration `038` is additive and
   idempotent, with no destructive changes to existing tables.
3. **Sequential execution is a database property.** `claim_next_subtask` takes a per-task row
   lock and only starts the first active row whose dependencies are finished, so two workers
   cannot interleave sibling subtasks even if they both call the API.
4. **Refiner patches are all-or-nothing.** Validation happens in memory; persistence compares
   expected statuses inside one transaction, deletes/updates/inserts, then rewrites dependency
   IDs and ordinals. A rejected patch writes no patch row.
5. **Reporter is an aggregator.** It has no agent call and generates no findings; a per-task
   primary key plus `ON CONFLICT DO NOTHING` makes "runs once" a storage guarantee.
6. **Memorist fails closed.** No tenant → no reads. Redaction runs before storage, and reads
   additionally filter `redacted = TRUE`.
7. **Flag wiring only.** `ARGUS_HIERARCHICAL_DELEGATION` resolves through
   `hierarchical_delegation_mode()`, but no production dispatcher path dispatches delegation
   tasks yet; that is Stage 4 integration, not a P-requirement.

---

## 6. Known limits (not P-requirement failures)

- The PentAGI upstream commit is **not vendored** in this checkout. Upstream citations above
  name the pinned files required by plan §1 and the behaviour statements in plan §4.1; line
  ranges and symbol names were not re-read from the upstream source during this pass.
- No live LLM Generator/Refiner/specialist is called. The contracts are agent-agnostic and
  tested with scripted agents, which is what P-02/P-03/P-06/P-08/P-09/P-10/P-11/P-12 specify.
  A live-model run belongs to the Stage 4 integrated scenarios.
- The production dispatcher loop does not yet create tasks for claimed intents or persist
  action outcomes from the ReAct executor; that wiring is Stage 4 (integrated run) and is
  deliberately outside this workstream's gate.
- The MCP `task_generate_subtasks`, `task_refine_subtasks`, `task_progress` and `task_cancel`
  bridge endpoints from plan §6.5 are not added yet. The contracts they would call exist and
  are tested.
- Cancellation is represented by the `cancelled` status and the task/tool executor boundary;
  no cooperative cancellation token is threaded through the worker in this pass.
- Tests use a local PostgreSQL 16.2 instance, not the CI Postgres job. The CI job that runs the
  graph tests should include `tests/test_pentagi_delegation.py` and set `DATABASE_URL`;
  the test module skips cleanly when it is absent.
