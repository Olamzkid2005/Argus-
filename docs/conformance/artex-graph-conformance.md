# ARTEX conformance ledger — graph-backed exploration (A1–A5)

**Date:** 24 November 2026
**Plan:** `docs/conformance/argus_three_frameworks_implementation_conformance_plan.md` §3
**Reference pin:** ARTEX `94757c5d7e704ac1c095ee99e97d9ac4d9d428c5`
**Argus baseline for this pass:** `189f6fe4` plus the changes listed under *Gate findings*
**Authoritative backend:** PostgreSQL via `argus-workers/database` (see `authoritative-state-backend-note.md`)

Statuses follow the plan §7.3 rules: `PASS` needs a code path **and** a test that ran in this
checkout, plus runtime evidence for state-machine behaviour.

---

## 1. Verification commands and observed results

| Command | Result |
|---|---|
| `./venv/bin/python -m pytest tests/test_graph_planner.py tests/test_graph_repository.py tests/test_graph_ingestion.py -q -p no:randomly` | **150 passed** |
| `./venv/bin/python -m pytest tests/test_graph_claims.py -q -p no:randomly` | **15 passed** |
| `./venv/bin/python -m pytest tests/test_mcp_server.py -q -p no:randomly` | **113 passed** |
| `./venv/bin/python -m pytest tests/ -q -p no:randomly` | **5,958 passed, 11 failed, 39 skipped** — all 11 failures pre-date this work (4 × LLM key absent, 3 × `playwright` absent, 1 × GraphQL spec fixture, 2 × benchmark fixtures, 1 × `LlmCostTracker` drift) |
| `ruff check .` | clean |
| `./venv/bin/python scripts/check_graph_import_boundary.py` | clean (C-18 boundary) |
| `./venv/bin/python scripts/shadow_planner_comparison.py --json ../docs/conformance/shadow-planner-comparison.json` | gate **passes**, see §4 |

---

## 2. Requirement ledger

| ID | Reference behaviour | Argus implementation | Test proof | Runtime proof | Result | Deviation |
|---|---|---|---|---|---|---|
| A-01 | Same root domain/subdomain/URL with case, default-port, trailing-slash variations canonicalise to one asset; observations merge; parents stay valid | `database/graph_identity.py` (`canonicalize`, `parent_identity`), `database/graph_repository.py:ensure_asset`, `ingest_observation` | `tests/test_graph_repository.py::TestAssetCanonicalization::*` (7), `TestAssetIngestion::test_canonical_variants_share_parent_assets` | 150-test DB run above | PASS | none |
| A-02 | Same asset from two tools in one workspace → one asset, two observations | `database/graph_repository.py:ingest_observation`, `ingest_recon_outcomes` in `tasks/graph_ingestion.py` | `TestAssetIngestion::test_two_tools_merge_onto_one_asset_with_two_observations`, `TestCrossToolMerge::*` (3) | 150-test DB run; shadow scenario ingested 10 assets from one pass with 0 duplicates | PASS | none |
| A-03 | Same domain under two scopes → no merge/visibility leak | `rotate tenant boundary in migration 035`; `_resolve_tenant` in `database/dispatcher_graph.py`; `resolve_scope_tenant` | `TestAssetIngestion::test_two_scopes_do_not_merge_or_leak`, `TestTenantBoundary::*` (2) | 150-test DB run | PASS | none |
| A-04 | Intent/fact/finding anchored to an asset returns the exact relationship | `database/graph_repository.py:attach_anchor`, `attach_anchor_scope`, `find_anchors_for_node`; `migrations/033_graph_tables.sql` | `TestAnchors::*` (3), `TestAnchorCoverage::*` (3) | 150-test DB run | PASS | none |
| A-05 | Invalid/cross-engagement edge or out-of-scope anchor rejected before mutation, reason audited | `database/dispatcher_graph.py:attach_edge/attach_anchor` + `record_write_rejection`; ingestion records rejected observations | `TestWriteRejectionAudit::test_cross_engagement_edge_is_rejected_and_audited`, `::test_out_of_scope_anchor_is_rejected_and_audited`, `TestAssetIngestion::test_out_of_scope_observation_is_audited_but_not_usable` | 150-test DB run; shadow scenario recorded `db.shadow-lab.internal` as `out_of_scope` and never schedulable | PASS | none |
| A-06 | Burst of graph updates → one debounced planner wake, no lost event, bounded turns | `database/migrations/036_planner_event_loop.sql`, `DispatcherGraph.begin_planner_turn/consume_planner_events`, `tasks/graph_planner.py:run_planner_loop` | `TestOutboxPlanningLoop::test_burst_of_graph_events_becomes_one_planning_turn`, `::test_hot_planner_is_bounded_by_max_turns`, `::test_a_wake_that_arrived_while_idle_is_consumed_later`, `TestProductionDrainAndFlags::test_concurrent_drains_do_not_lose_or_double_consume_a_wake` | 150-test DB run; shadow run coalesced **11 queued events into one turn** | PASS | none |
| A-07 | Unmet goal with no open/running intent → at least one intent or a hard planner error; never silent completion | `orchestrator_pkg/planning/exploration_planner.py`, `PlannerHardFloorError` in `tasks/graph_planner.py` | `TestHardFloorAndProposalContract::test_unmet_goal_with_no_intent_hard_fails_loudly`, `::test_scheduled_work_satisfies_the_hard_floor` | 150-test DB run | PASS | Floor now also accepts already-scheduled todo work as "not a stall" (plan 3.5.5); see §3 |
| A-08 | Goal proven by verified evidence → goal concluded, no further intent for that goal | `database/graph_repository.py:prove_goal_from_findings` (+ provenance rule), `orchestrator_pkg/persistence/goal_proof.py` | `TestGoalProofFromVerifiedEvidence::*` (3), `TestGoalProofRequiresVerifierProvenance::*` (8), `TestPersistedProofCanConcludeAGoal::*` (2), `TestVerifierConcludesGoals::*` (6) | 150-test DB run; verifier save path concludes the goal without a dispatcher call | PASS | none |
| A-09 | Open/running intent or existing evidence already covering the direction → no duplicate intent | `ExplorationPlanner.plan` (open intents, `open_gap_keys`), `apply_intent_proposals` duplicate suppression | `test_duplicate_and_already_proven_intents_are_suppressed`, `test_scheduled_gap_work_is_not_duplicated_by_the_planner`, `test_a_capped_frontier_still_covers_every_untested_class` | Shadow gate: with 6 gaps scheduled the planner proposed **0** duplicates; without scheduling it proposed the untested classes | PASS | Fixed during the gate, see §3 |
| A-10 | Three-step dependent investigation: step N+1 cannot dispatch before step N's fact | `planner_todos.depends_on` prerequisite clause in `claim_recon_todo` | `TestDependencyAwareClaims::test_dependent_todo_is_refused_until_prerequisite_completes` | 150-test DB run | PASS | none |
| A-11 | Live claim not stolen; expired claim reclaimable after the lease; heartbeat cadence default 15s / 90s TTL | `database/graph_claims.py` (one protocol for todos and intents), `claim_recon_todo`, `claim_intent_node` | `TestClaimFencingAndHeartbeat::test_heartbeat_keeps_live_claim_and_expired_lease_reports_loss`, `TestWorkerIntentProtocol::test_an_expired_intent_claim_is_reclaimable_and_fenced_like_a_todo`, `tests/test_graph_claims.py` | 150 + 15-test DB runs | PASS | Artefacts use the implemented 300 s todo lease / 90 s intent lease; the ARTEX 15 s heartbeat cadence is a deployment setting, not a code default |
| A-12 | Old worker submits after takeover → fencing token rejects, nothing committed | `claim_token::text = %s` live-claim predicate in `graph_claims.live_claim_sql`, used by heartbeat/complete/release | `TestClaimFencingAndHeartbeat::test_stale_token_write_is_rejected_after_reclaim`, `TestWorkerIntentProtocol::test_worker_claims_one_intent_at_a_time_with_token_and_lease` | 150-test DB run | PASS | none |
| A-13 | Worker B retrieves worker A's trace instead of repeating the action | `DispatcherGraph.record_trace/search_traces`, `tests` + MCP `graph_search_traces` | `TestWorkerIntentProtocol::test_trace_search_is_engagement_scoped_and_untrusted` | 150-test DB run | PASS | none |
| A-14 | Prompt injection in response/trace cannot add goals, change scope, prove a goal or authorise a target | `sanitize_untrusted_text`, goal nodes operator-created only, planner reads untrusted text as data | `TestPromptInjectionIsolation::*` (2), `TestGoalProofRequiresVerifierProvenance::test_scanner_self_reported_verified_flag_is_not_provenance` | 150-test DB run | PASS | none |
| A-15 | Restart after a planner todo is written → todo state and dependency order survive | `planner_todos` persistence (`migrations/037_graph_production_loop.sql`), `schedule_coverage_gaps` idempotency | `TestDependencyAwareClaims::test_pending_chain_survives_restart_without_early_dispatch` | 150-test DB run | PASS | none |
| A-16 | Same action/result delivered twice → one logical graph update | `DispatcherGraph.record_action` idempotent ledger, `ingest_observation` replay idempotency | `TestActionLedgerIdempotency::*` (2), `TestAssetIngestion::test_replayed_observation_is_idempotent` | 150-test DB run | PASS | none |

---

## 3. Gate findings and the fixes they required

The shadow comparison (A5) found two contract gaps that the deterministic plan hid:

1. **The planner ignored the persistent todo list (plan §3.5.5, A-09).** With the
   coverage scheduler active, class work is already committed as gap todos, but the
   planner only consulted *open intents*. Any engagement whose gaps are all
   class-verify hints (no `expand` intent node) would have had the planner propose
   per-asset intents that duplicate scheduled recon.
   Fixed: `planner_overview` now exposes `open_gap_keys`; `ExplorationPlanner` skips
   classes that already have a scheduled gap; `run_planner_turn` counts scheduled
   todos as satisfying the A-07 floor. Tests:
   `test_scheduled_gap_work_is_not_duplicated_by_the_planner`,
   `test_scheduled_work_satisfies_the_hard_floor`.
2. **A capped frontier spent its whole budget on one class.** The overview is ordered
   by asset type, so `max_intents=5` proposed five endpoints and left `ip`, `service`,
   `subdomain` and `root_domain` unrepresented — i.e. the planner's frontier was not
   comparable to the deterministic plan's class coverage.
   Fixed: `_breadth_first` interleaves classes so a capped frontier covers every
   untested class before going deeper. Test:
   `test_a_capped_frontier_still_covers_every_untested_class`.

---

## 4. A5 gate — shadow comparison result

Artifact: `docs/conformance/shadow-planner-comparison.json`
Harness: `argus-workers/scripts/shadow_planner_comparison.py` (rebuilds both scratch
engagements on every run, so the result is reproducible)

Scenario shape: one realistic assessment (`shadow-lab.internal` with `*.shadow-lab.internal`
and `10.42.0.0/28` approved), one operator goal, one recon pass producing 10 in-scope
assets plus one out-of-scope discovery (`db.shadow-lab.internal`, correctly rejected).

| Check | `with_scheduler` | `planner_only` |
|---|---|---|
| Recon ingestion | 10 accepted / 1 rejected (out of scope) / 0 failed | same |
| Deterministic coverage scheduler | 6 gaps: 1 × `undiscovered_scope_entry`, 5 × `untested_asset_class` | not run |
| ARTEX planner (shadow) | 11 events consumed in 1 turn, **0 proposals** (no duplicate direction) | 11 events in 1 turn, **5 proposals**, one per untested class |
| Intents created / work dispatched | 0 / 0 | 0 / 0 |
| Durable state before → after | intents 1 → 1, todos 6 → 6, outbox drained | intents 0 → 0, todos 0 → 0, outbox drained |

Agreement:

- deterministic untested classes `[endpoint, ip, root_domain, service, subdomain]` **=**
  planner proposed classes (same set) → `same_classes: true`
- planner emits no duplicate direction once the scheduler has committed work →
  `duplicate_direction_suppressed: true`
- shadow wrote nothing in both runs → `shadow_wrote_nothing: true`

**Adaptation (not a defect):** approved-but-undiscovered scope entries
(`api.shadow-lab.internal`) can only be dispatched by the deterministic scope-entry gap,
because an asset-driven planner has no asset to anchor a proposal to. The two paths are
therefore complementary, not interchangeable: the deterministic scheduler feeds scope
entries, the ARTEX planner proposes class/asset work. Running both with
`ARGUS_GRAPH_EXPLORATION=on` is the intended configuration.

**Gate verdict:** the shadow comparison passes. The A5 conditions for enabling execution
(shadow agreement, no duplicate dispatch, no writes in shadow, one-switch rollback proven by
`test_rollback_is_one_switch_and_needs_no_data_repair`) are met. Rollback remains
`ARGUS_ORCHESTRATION_V2=off`.

---

## 5. Known limits (not A-requirement failures)

- The comparison target is Argus's deterministic **coverage scheduler** in the
  Python/PostgreSQL path. The TUI phase plan is a separate execution mode (see
  `authoritative-state-backend-note.md`) and is not exercised by this gate.
- The stress/live-lab runtime proof is limited to the local fixture assessments used by
  the DB-backed tests and this harness; no live customer target was scanned.
