# Stage 5 — Gradual production activation plan

**Plan ref:** `argus_three_frameworks_implementation_conformance_plan.md` §Stage 5.
**Status:** pre-rollout. No live engagement has V2 enabled. This document defines
the gate **before** any rollout, as the plan requires ("thresholds defined before
rollout; do not use raw finding count as the success metric").

## 1. What already exists (no new mechanism needed)

- **One-switch rollback:** `ARGUS_ORCHESTRATION_V2=off` → the production planner
  drain does nothing and the legacy workflow path keeps running
  (`orchestrator_pkg/planning/flags.py`: `effective_mode()`,
  `legacy_rollback_enabled()`). Rollback is a single env change plus process
  restart; no migration, no data rewrite.
- **Shadow comparison:** `scripts/shadow_planner_comparison.py` plus the
  `shadow_mode_stats` table (migration 010) — the Stage 4 activation evidence
  for `ARGUS_GRAPH_EXPLORATION=on`.
- **Cost raw material:** `tool_metrics` (migration 005/010) records per-tool
  `duration_ms`/`success` per engagement via `ToolMetricsRepository`.
- **Run outcomes:** `control_plane_tasks.status`
  (`running|succeeded|failed|cancelled|rejected|timed_out`),
  `control_plane_reason_checkpoints.last_outcome`, `delegation_tasks.status`,
  `delegation_patches` (refinements), `graph_anchor_scopes.coverage_state`.

## 2. Rollout scope (explicitly scoped engagements)

1. V2 is enabled per engagement by allowlisting engagement IDs in operator
   config. Anything not allowlisted stays on the legacy path.
2. First cohort: **3–5 controlled lab engagements** with written authorization,
   matching the Stage 4 lab discipline (scope, egress, budget, approval).
3. No customer / production-target engagement enters the cohort until the gate
   in §4 passes on the lab cohort.
4. Engagement allowlisting is a named follow-up (operator config + dispatcher
   check, default deny). Until it lands, V2 stays `off`/`shadow` globally.

## 3. The nine Stage 5 metrics (definitions + source tables)

All metrics are computed per cohort window by `control_plane/rollout_metrics.py`
from a snapshot (see §5). Rates are fractions in `[0, 1]` unless noted.

| # | Metric | Definition | Source |
|---|--------|-----------|--------|
| 1 | no-stall rate | engagements with zero `timed_out` control-plane tasks and no terminal stall checkpoint ÷ engagements observed | `control_plane_tasks`, `control_plane_reason_checkpoints` |
| 2 | duplicate intent rate | intents rejected/deduped as duplicates ÷ intents proposed (target: 0) | reason decisions, `graph_nodes` |
| 3 | subtask refinement count | mean `delegation_patches` rows per finished task (informational, capped) | `delegation_patches`, `delegation_tasks` |
| 4 | claim-loss count | renewed/expired `reason` leases lost to another worker (target: 0) | `control_plane_leases`, dispatcher logs |
| 5 | verified-finding ratio | verified findings ÷ total findings (**never** raw finding count) | findings + verifier evidence |
| 6 | coverage | anchors `covered` ÷ anchors in scope | `graph_anchor_scopes.coverage_state` |
| 7 | LLM/tool cost | USD per engagement from operator rate card × (`tool_metrics.duration_ms`, LLM token logs); hard per-engagement budget cap | `tool_metrics`, LLM logs |
| 8 | partial-run rate | engagements ending `PARTIAL`/`INTERRUPTED` ÷ engagements observed | dispatcher terminal states |
| 9 | recovery rate | crashed/stale runs resumed with evidence intact ÷ recovery attempts | reconcile paths, `delegation_subtasks` resume |

## 4. Pre-rollout thresholds (the gate)

Evaluated on the lab cohort. **GO** requires every row to pass; anything else is
**NO-GO** (fail closed — V2 stays off/shadow).

| Metric | Threshold |
|---|---|
| engagements observed | ≥ 3 (below this the verdict is INSUFFICIENT DATA, never GO) |
| no-stall rate | ≥ 0.95 |
| duplicate intent rate | = 0 |
| subtask refinements | mean ≤ 3 per finished task |
| claim-loss count | = 0 |
| verified-finding ratio | ≥ 0.50 |
| coverage | ≥ 0.80 of in-scope anchors |
| LLM/tool cost | ≤ operator per-engagement budget cap (set in the cohort record) |
| partial-run rate | ≤ 0.10 |
| recovery rate | ≥ 0.90 (vacuous ≥ requires ≥ 1 attempt; zero attempts → INSUFFICIENT DATA) |

Raw finding count is recorded for context only and **cannot** flip a NO-GO to GO.

## 5. Snapshot format and evaluator

`control_plane/rollout_metrics.py::evaluate_rollout_snapshot(snapshot,
thresholds)` is pure (stdlib only): counts in, verdict out. The snapshot is a
plain dict collected by the operator from the tables in §3, e.g.:

```json
{
  "engagements_observed": 4,
  "stalled_engagements": 0,
  "duplicate_intents": 0,
  "intents_proposed": 38,
  "refinements_total": 9,
  "tasks_finished": 4,
  "claim_losses": 0,
  "verified_findings": 11,
  "total_findings": 17,
  "anchors_covered": 41,
  "anchors_in_scope": 48,
  "cost_usd": 12.40,
  "cost_budget_usd": 50.0,
  "partial_runs": 0,
  "recovery_attempts": 2,
  "recoveries_intact": 2
}
```

Verdict is one of `GO`, `NO-GO` (with breached rows listed), or
`INSUFFICIENT DATA` (too few engagements, missing fields, or zero recovery
attempts). Missing/negative inputs fail closed to `NO-GO`/`INSUFFICIENT DATA`,
never GO.

## 6. Rollback procedure

1. Set `ARGUS_ORCHESTRATION_V2=off` in the deployment config; restart workers.
2. Confirm `mode_report()["effective"] == "off"` on the health endpoint.
3. In-flight V2 tasks drain under their leases; new work takes the legacy path.
4. Record the rollback and the breaching metric in the cohort record (§7).

## 7. Gate decision record (fill at rollout time)

- Cohort engagements: …
- Snapshot + evaluator verdict: …
- Decision (GO / NO-GO) + approver: …
- Threshold changes, if any, with justification (changing a threshold to pass is
  a plan deviation and must be recorded in `deviations.md`).
