# Integrated end-to-end results (Stage 4)

**Date:** 25 November 2026
**Plan:** `argus-workers/docs/conformance/argus_three_frameworks_implementation_conformance_plan.md` §7.5 and §8 Stage 4
**Runtime:** PostgreSQL 16.2 with migrations through `040_control_plane.sql`

**Command:**

```bash
cd argus-workers && \
  DATABASE_URL="postgresql://postgres:@/postgres?host=/tmp/deleg-pg" \
  python -m pytest tests/test_stage4_integration.py -q -p no:randomly
```

**Result:** **9 passed, 0 skipped** (2026-11-25). The same run combined with
`tests/test_control_plane.py`, `tests/test_control_plane_bridge.py`,
`tests/test_pentagi_delegation.py` and `tests/test_celery_app.py` reports
**96 passed**.

## What is now integrated

| Component | Path |
|---|---|
| Dispatcher tick / contracts / leases | `control_plane/` |
| Typed `task_*` MCP transport | `control_plane/worker_bridge.py`, `control_plane/task_service.py`, `mcp_server.py` |
| Intent → Task → Subtasks (dispatcher-owned) | `agent/delegation/integration.py` (`IntentTaskRunner`) |
| In-process integrated worker | `control_plane/integrated.py` (`IntegratedWorkerRunner`, `build_integrated_runner`) |
| Scheduled loop | `tasks/control_plane.py` (`tasks.control_plane.tick`, 60 s beat) |

`run_control_plane_tick` selects, in order: an explicitly injected runner, the
stdio MCP task bridge (`ARGUS_TASK_WORKER_CMD`), or the integrated runner
(`ARGUS_INTEGRATED_TASK_AGENTS=module:factory`). In all three cases the
dispatcher remains the only writer of graph, lease and task state.

The remaining typed endpoints from plan §6.5 are implemented:
`task_generate_subtasks`, `task_refine_subtasks`, `task_progress` and
`task_cancel` validate bounded payloads and return normalised data. They never
write durable state; the dispatcher applies their result.

## Scenario results

| Scenario | Test | Result |
|---|---|---|
| 1 — Happy path: bootstrap fact, two intents, task plan, sequential subtasks, refiner add, one explore fact, report/actions/patch persisted, reason re-eligible | `test_scenario1_bootstrap_reason_explore_end_to_end` | PASS |
| 2 — No stall with an unresolved goal and no intents; duplicate intent and duplicate explore result write nothing | `test_scenario2_no_stall_and_no_duplicates` | PASS |
| 3 — A→B→C dependency order, restart between steps, order preserved | `test_scenario3_dependency_chain_survives_restart` | PASS |
| 4 — Expired claim rejects the old worker's result; a fresh worker can reclaim | `test_scenario4_expired_claim_rejects_the_old_worker` | PASS |
| 5 — Refiner ADD/REMOVE/REORDER preserves completed evidence; restart reconciles; reflection stops at 3 | `test_scenario5_refiner_patch_preserves_completed_evidence`, `test_scenario5_restart_reconciles_and_reflection_stops_at_three` | PASS |
| 6 — Complete+intents and conclude-with-completion are rejected with no graph write | `test_scenario6_invalid_worker_results_write_nothing` | PASS |
| 7 — Two engagements and two workers keep facts/tasks isolated; second dispatcher is not leader | `test_scenario7_engagements_and_dispatchers_stay_isolated` | PASS |
| 8 — Hostile evidence stays data; agent/executor payloads are bounded; worker graph write is denied | `test_scenario8_hostile_evidence_stays_bounded` | PASS |

## Limits of this evidence

- Every agent is a deterministic fake. No live LLM Generator, Refiner,
  specialist or Repair agent ran; those adapters are supplied by
  `ARGUS_INTEGRATED_TASK_AGENTS`.
- No live network target was scanned. The security scenario proves payload
  bounds and the graph-write boundary, not tool-level scope/egress enforcement,
  which remains covered by the existing scope/budget test suites.
- Controlled-lab comparison against the legacy workflow is still an operational
  step; the shadow comparison evidence for the graph planner remains in
  `graph-exploration-conformance.md`.
