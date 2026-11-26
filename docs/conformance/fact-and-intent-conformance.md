# Fact-and-intent real-boundary conformance (Stage 4)

**Date:** 26 November 2026
**Plan:** `docs/conformance/argus_three_frameworks_implementation_conformance_plan.md` §5 (fact-and-intent
protocol), §7.5 (scenarios 1, 3–8), §7.6 (this artefact)
**Reference pin:** fact-intent protocol `8e7e0ea67552383851cfabfba0c4e9d9c007878` (per `reference-pins.md`)
**Argus baseline for this pass:** `1fb116b2` plus the uncommitted Stage 4 real-boundary work listed
under *Implementation surfaces* below
**Authoritative backend:** PostgreSQL via `argus-workers/database` (see `authoritative-state-backend-note.md`)

Statuses follow the plan §7.3 rules: `PASS` needs a code path **and** a test that ran in this checkout,
plus runtime evidence for state-machine behaviour. No fake-backed demos: the tests below execute the
integrated chain (dispatcher tick → strict contracts → delegation hierarchy → executor → graph
write-back) with the production `RealToolExecutor` wherever a tool runs. The only doubles are the
Generator/Reasoner/Bootstrapper adapters (LLM roles with no deterministic substitute in this
environment) and explicitly marked slow-path probes. No test fabricates tool output.

---

## 1. Verification commands and observed results

Run on 26 November 2026 against local PostgreSQL **15.17** (`postgres@localhost:5432/argus_stage4`),
with the migration runner applied through `041_delegation_tool_routing.sql` (verified: `_migrations`
latest is `041_…`; `delegation_subtasks` carries the `tool` / `arguments` routing columns).

| Command | Result |
|---|---|
| `cd argus-workers && DATABASE_URL=postgresql://postgres@localhost:5432/argus_stage4 venv/bin/python -m pytest tests/test_stage4_real_boundary.py -q` | **23 passed** |
| `cd argus-workers && DATABASE_URL=… venv/bin/python -m pytest tests/test_stage4_real_boundary.py tests/test_pentagi_delegation.py tests/test_control_plane.py tests/test_control_plane_bridge.py tests/test_stage4_integration.py tests/test_tool_cache.py tests/test_install_tools.py -q` | **163 passed** |
| `cd Argus-Tui/packages/opencode && bun typecheck` (`make typecheck-v5`) | **exit 0** (`tsgo --noEmit`, no errors) |
| `cd Argus-Tui/packages/opencode && bun test test/argus/ --timeout 30000` (`make test-v5`) | **see §6** — run launched; full-suite result recorded on completion |
| `cd argus-workers && git diff --check` | clean (no whitespace errors introduced) |

Suite counts above are from runs against the reachable test database, not from collection-only passes.

Real binaries exercised on this pass: `nuclei` (`/Users/mac/go/bin/nuclei`, `-version` only),
`eslint` (JSON findings against a local `eslint.config.mjs` + fixture), `/bin/sleep` (lease/cancel
probes). `semgrep`/`bandit` are **not** exercised on the real path in this environment: under the
`ToolRunner` locked environment (`PYTHONPATH` pinned to the venv 3.11) the Homebrew `python3.14`
shims fail with `SRE module mismatch`, so no claim is made for them here (see `deviations.md`).

---

## 2. Implementation surfaces

```text
argus-workers/agent/delegation/tool_executor.py   RealToolExecutor (production executor),
                                                  validate_approval, HIGH_IMPACT_TOOLS gate,
                                                  eslint/semgrep result parsers,
                                                  ToolCallSpecialistRunner, default registry,
                                                  cache_mode passthrough (NO_CACHE support)
argus-workers/agent/delegation/integration.py     IntentTaskRunner: lease heartbeat,
                                                  stale-RUNNING auto-reconcile, WAITING resume
argus-workers/agent/delegation/generator.py      subtask tool/arguments validation
argus-workers/agent/delegation/store.py          tool/arguments persistence (insert_plan)
argus-workers/agent/delegation/models.py        SubtaskDraft tool/arguments fields
argus-workers/agent/delegation/primary.py       production-executor default wiring
argus-workers/control_plane/contracts.py        ExploreFinding.source_agent; Explore
                                                  contract extended (findings/anchors/todos)
argus-workers/control_plane/store.py            source_agent persisted into finding evidence
argus-workers/control_plane/dispatcher.py       flag gate (planner defer), cancel kills the
                                                  real tool process, GraphClaimLostError
                                                  mid-run → fail Exploration + "cancelled"
argus-workers/control_plane/integrated.py        production executor default; heartbeat
                                                  closure ownership
argus-workers/tasks/control_plane.py            Celery beat tick (docstring now names both
                                                  transports; see §5)
argus-workers/tasks/graph_planner.py            flag ownership (fact-intent on → planner
                                                  loop defers) + shared normalized-objective
                                                  cross-dedupe in apply_reason
argus-workers/tools/tool_runner.py              tool-result cache gated on _cacheable
                                                  (success / findings exit codes only)
argus-workers/database/migrations/041_delegation_tool_routing.sql
                                                  tool/arguments plan columns
argus-workers/tests/test_stage4_real_boundary.py 23 real-boundary tests (this pass)
```

Design boundaries (unchanged from the control-plane pass):

- Only `PostgresControlPlaneStore` / `PostgresDelegationStore` write durable state; the dispatcher
  still parses every reply with the strict contracts and performs the graph write, so no adapter can
  commit a fact by itself.
- Workers receive only a bounded JSON job: no claim token, no database URL, no write authority
  (proven by `test_executor_request_and_env_carry_no_credentials`, including the `ToolRunner`
  locked environment carrying no `DATABASE_URL` and no `*token*` keys).

---

## 3. Requirement evidence — the 23 real-boundary tests

### 3.1 Real tool execution with enforced gates (§5 scope/egress/budget/approval; §7.5 scenario 8)

| Test | What runs for real | Result |
|---|---|---|
| `test_real_executor_runs_nuclei_and_records_action` | `nuclei -version` via `ToolRunner.run`; action persisted with outcome `completed` | PASS |
| `test_real_executor_scope_refusal_is_recorded` | `httpx https://other.example/` against an engagement scoped to `fixture.example`; the real scope/egress gate refuses, outcome `refused` recorded with `check` ∈ {scope, egress} and a reason | PASS |
| `test_real_executor_approval_refusal_without_record` | `sqlmap` (a `HIGH_IMPACT_TOOLS` member) with no `arguments.approval.by`; refused **before any process spawns**, `check` = approval | PASS |
| `test_validate_approval_branches` | Pure gate branches: non-impact tools pass; impact tools need `approval.by`; blank `by` fails; lone informational argv (`-version`) is exempt | PASS |
| `test_real_executor_budget_refusal` | `Governance(engagement_id, max_tokens=1)` spent budget refuses `nuclei -version` before spawn, `check` = budget | PASS |
| `test_real_executor_dangerous_payload_fails_closed` | `sleep` with a `$(rm -rf /)` payload trips `is_dangerous` → `SecurityError`; **no result fabricated**, subtask `failed` with "fail closed" in `last_error` | PASS |

Approval-gate semantics proven: `HIGH_IMPACT_TOOLS` require `arguments.approval.by`; a lone
informational flag (`-version`/`-h`, no target) is exempt. All refusals are recorded on the real
adapter with outcome `refused` in the recorded result — nothing is refused on a fake.

### 3.2 Specialist delegation on the real path (§7.5 scenario 8, specialist + fallback tools)

| Test | Result |
|---|---|
| `test_specialist_eslint_merges_real_findings` — bounded `ToolCallSpecialistRunner` runs real `eslint --format json` on a local fixture; `no-console` + `no-eval` findings merge with `source_agent: specialist:static-analyzer` provenance; the specialist request carries no `database_url` / `claim_token` | PASS |
| `test_parse_eslint_json_pure` — parser unit: severities, confidence, title shape; non-eslint output yields no findings | PASS |

### 3.3 Full lifecycle: fact + findings + anchors + edges + todos (§7.5 scenario 1)

| Test | Result |
|---|---|
| `test_full_lifecycle_conclusion` — `bootstrap → reason → explore` ticks on the integrated runner; explore concludes exactly one Fact; eslint findings persist as `PENDING` with `provenance: delegation` + `delegation_task_id` evidence; the plan-declared anchor (`probe-app`, `covered`) and todo (`verify eslint findings`) persist; a `derived_from` edge targets the conclusion | PASS |
| `test_unproven_finding_cannot_prove_goal` — the A-08 gate holds on the integrated path: `prove_goal_from_findings` with a `PENDING` (unverified) finding raises `GraphMutationError`; the goal stays `open` | PASS |

### 3.4 Heartbeat, reconcile, waiting, cancellation (§7.5 scenarios 3, 4, 6)

| Test | Result |
|---|---|
| `test_heartbeat_renews_claim_across_long_task` — three real 1-second sleeps under a **2-second** explore lease conclude `succeeded` because the dispatcher-owned heartbeat closure renews the claim in flight; without renewal the same shape lapses (next test) | PASS |
| `test_expired_claim_rejects_late_conclusion` — an un-renewed 1s lease lapses; the late `conclude_explore` raises `LateResult` (fencing token enforced, no stale write) | PASS |
| `test_crash_self_heals_without_manual_reconcile` — a subtask stuck `RUNNING` (simulated crash between steps) is auto-reconciled on retry; all subtasks finish with no operator reconcile call | PASS |
| `test_waiting_resumes_with_operator_answer` — `WAITING` surfaces as `waiting_in_progress`; an operator answer resumes the same task to `finished` (serial-dependency state survives the pause) | PASS |
| `test_cancel_during_call_stops_real_tool` — cancel mid-`sleep 30` (NO_CACHE, so a real process is registered) kills the real process via the process registry; `run_explore` returns `"cancelled"`; **no conclusion is written** (only the origin fact remains); mid-run `GraphClaimLostError` is handled the same way | PASS |

Heartbeat ownership (documented limitation): the renewal closure is passed only to executors that
advertise heartbeat support; the stdio `task_*` bridge path has no in-flight heartbeat — a long
stdio explore relies on the crash/reconcile path instead. See `deviations.md`.

### 3.5 Single autonomous intent generator + flags (§5 single-generator; §7.5 scenario 2)

| Test | Result |
|---|---|
| `test_both_flags_on_cannot_double_dispatch` — with `ARGUS_FACT_INTENT_PROTOCOL=on` **and** `ARGUS_GRAPH_EXPLORATION=on`, `run_planner_turn` creates nothing and reports `deferred_to_reason`; one normalized objective yields exactly one intent, and the second planner turn still creates nothing | PASS |
| `test_reason_path_suppresses_planner_duplicate` — normalized-objective cross-dedupe in `apply_reason`: a reason intent matching an existing planner intent (case-insensitive) creates no duplicate | PASS |
| `test_flag_off_creates_no_delegation_task` — with `ARGUS_HIERARCHICAL_DELEGATION=off`, explore dispatches nothing and no delegation task row exists | PASS |
| `test_reason_job_carries_graph_overview` — the reason job carries the §5.2B overview: untested assets, anchors with coverage, open-todo count, goals and facts | PASS |

### 3.6 Isolation and evidence integrity (§7.5 scenario 7; §7.5 scenario 6 failure paths)

| Test | Result |
|---|---|
| `test_traces_stay_engagement_scoped` — trace search never crosses the engagement boundary | PASS |
| `test_recording_executor_fails_closed_on_lost_evidence` — a completed action whose record write throws raises `DelegationError("fail closed")`; skipped actions annotate `evidence_incomplete` instead of raising (`test_recording_executor_annotates_non_consequential_gap`) | PASS |

---

## 4. Boundary-trial fixes made during this pass (no fake-backed demos)

1. **`source_agent` contract rejection → silent conclude fallback, no findings.** The explore contract
   rejected the specialist finding field, the strict parser fell back to a bare conclusion, and
   findings were silently dropped. Fixed: `ExploreFinding` now carries `source_agent`, persisted
   into finding evidence by `control_plane/store.py`.
2. **Claim lost mid-run recorded as failed.** A `GraphClaimLostError` raised while a worker was
   finishing was recorded as a failure. Fixed: the dispatcher catches it mid-run, fails the
   Exploration task explicitly, and `run_explore` returns `"cancelled"` — indistinguishable from an
   operator cancel, with no graph write.
3. **Tool-result cache poisoning the cancel probe.** A cached `sleep 30` success (exit 0, 30 s
   duration recorded) replayed instantly, so no real process was ever registered and the cancel test
   could not prove a kill. Fixed at two levels: `tool_runner.py` only caches `_cacheable` results
   (exit 0 or known findings-exit-codes — a killed/failed result is never replayed), and
   `RealToolExecutor` accepts `arguments.cache_mode` (`NO_CACHE` used by the cancel test).
   The instant-`sleep` mystery during diagnosis was this cache replay, not a timeout bug.

---

## 5. Collateral corrections in this pass

- **Stale count 38 → 40:** `tests/test_control_plane.py` + `tests/test_control_plane_bridge.py` now
  collect and pass **40** tests (two worker-failure/commit-guard regression tests were added after
  the 38-pass run was recorded). `control-plane-conformance.md` and all 25 count references in
  `requirements.json` now read `40 passed, 0 skipped (2026-11-26)`.
- **Stale `tasks/control_plane.py` docstring:** it claimed workers come only from the typed stdio
  `task_*` MCP bridge. The tick actually prefers `ARGUS_TASK_WORKER_CMD` and falls back to the
  integrated in-process runner (`ARGUS_INTEGRATED_TASK_AGENTS`), whose explore path runs the
  production `RealToolExecutor` by default. The docstring now names both transports.

---

## 6. Full-suite results (`make test-v5` / `make typecheck-v5`)

- `make typecheck-v5` → `cd Argus-Tui/packages/opencode && bun typecheck` → **exit 0**.
- `make test-v5` → `cd Argus-Tui/packages/opencode && bun test test/argus/ --timeout 30000` →
  launched 26 November 2026 as a detached run (the suite takes >10 minutes in this environment;
  per-test CLI spawns cost ~2.5 s each). Result and exit code recorded below on completion.
  No TypeScript file was changed in this pass (`git status` shows only `argus-workers/**` and
  `docs/**`), so any `test-v5` failure is definitionally independent of this change; unexpected
  failures are checked against the pre-existing baseline before being attributed.

**test-v5 outcome (recorded 26 November 2026):** `1728 pass, 2 skip, 6 fail` across 109 files
(796 s wall-clock), **exit code 1**. The 6 failures are pre-existing/environmental, not attributed
to this pass: zero `Argus-Tui/**` files changed here (`git diff --name-only` shows only
`argus-workers/**` and `docs/**`), five are subprocess-spawn timeouts (`assess`/`doctor`/`tools`
handlers at the 15 s timeout, two `Assess Flow` pipeline tests at the 30 s timeout — sandbox spawn
slowness), and the sixth (`EngagementStore … response_evidence existed still opens`, a TS-side
SQLite migration test) **passes in isolation** (17 pass / 0 fail when its file is run alone), i.e.
it is flaky under full-suite load, not a regression. See `deviations.md` §3 for the standing
open-gate items (live-lab target, live LLM), which this environment cannot perform.

---

## 7. What is deliberately NOT claimed

- No live-lab network target was authorized or used; tool runs are hermetic (`nuclei -version`,
  local `eslint`, `sleep`) or refused by the gates. Live-network behaviour is an open gate item in
  `deviations.md`, not a pass.
- No live LLM was called; Generator/Reasoner/Bootstrapper remain test doubles with the real
  executor underneath. Single-generator enforcement is proven structurally (flag ownership +
  normalized-objective dedupe), not against two live planners.
- Lease-renewal is proven with a 2-second lease outlasted by heartbeated work (and the lapse path
  without renewal); the production default claim lease is 90 s (`claim_explore` /
  `dispatcher.run_explore` defaults). A >90 s wall-clock renewal run was not executed in this pass.
- `semgrep`/`bandit` parsers exist and are unit-tested, but the binaries cannot run under the
  `ToolRunner` locked environment on this host; they are not part of the real-path evidence.
