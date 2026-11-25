# Fact-and-Intent Control Plane Conformance (C-01…C-22)

**Scope:** the dispatcher-owned `bootstrap`, `reason` and `explore` protocol from
the implementation plan §5 (single dispatcher, typed results, leases,
checkpoints, worker registry, cancellation).

**Runtime:** PostgreSQL 16.2 with the migration runner through
`040_control_plane.sql`.

**Command:**

```bash
cd argus-workers && python -m pytest tests/test_control_plane.py -q -p no:randomly
```

**Result:** **38 passed, 0 skipped** (2026-11-25) across
`tests/test_control_plane.py` (DB-backed) and
`tests/test_control_plane_bridge.py` (typed transport, no database).

## Ownership

- `control_plane/contracts.py` — strict result parsers. Unknown keys, missing
  fields, empty descriptions, wrong types, invalid fact IDs and conflicting
  `complete` + `intents` forms are rejected before any write. The singular
  `intent` alias is accepted only with `allow_legacy_intent=True` and logs a
  deprecation warning.
- `control_plane/scheduler.py` — support, capacity, health, temporary
  unavailability, priority, running count, warm-engagement preference and a
  deterministic tie-break (injectable RNG).
- `control_plane/store.py` — dispatcher-owned persistence: worker registry,
  dispatcher/reason leases with fencing tokens, task records, reason
  checkpoints, reserved bootstrap intent, and every graph write through
  `DispatcherGraph`.
- `control_plane/dispatcher.py` — exactly one leadership lease per engagement,
  one protocol step per tick, result validation, same-session conclude
  fallback, lease-loss/cancellation guards.
- `control_plane/worker_bridge.py` — the live `WorkerRunner`: a newline-delimited
  JSON-RPC stdio client for the typed `task_bootstrap` / `task_reason` /
  `task_explore` methods. It starts `mcp_server.py` (or
  `ARGUS_TASK_WORKER_CMD`), enforces request/response size limits, maps a
  read timeout to `TimeoutError` and a bad reply to `ProtocolError`.
- `control_plane/task_service.py` — the server side of that protocol. It accepts
  only the exact envelope (`schema_version`, `task_type`, `conclude`,
  `request`), caps the payload at 256 KiB and runs the configured executor. No
  executor configured means an explicit `accepted=false` rejection, never a
  fabricated fact.
- `tasks/control_plane.py` — the Celery beat tick. It lists active engagements,
  takes the per-engagement dispatcher lease, runs at most one step, and reports
  `unconfigured` when no worker transport or `ARGUS_FACT_INTENT_PROTOCOL=on` is set.
- Workers receive only a bounded JSON job. It contains no claim token, no
  database URL and no write authority.

**Commit guards.** Bootstrap and reason results are committed only when the
engagement is still active and the task that produced them is still `running`.
`_require_live_task` cancels the task (and the dispatcher releases the bootstrap
reservation) when either condition fails, so a cancellation that lands while a
worker is finishing cannot turn into a fact or a new intent. Explore already had
the equivalent guard. Regression tests:
`test_bootstrap_result_rejected_when_engagement_stops`,
`test_bootstrap_result_rejected_when_task_is_cancelled`,
`test_reason_result_rejected_when_engagement_stops`,
`test_reason_result_rejected_when_task_is_cancelled`.

**Conclude fallback policy.** Only a timeout (`TimeoutError`) or a contract
violation (`ProtocolError`, including `accepted=false`) may invoke the
same-session conclude prompt. An executor crash, a store failure or a
programming error never runs the fallback: bootstrap releases its reservation
and explore fails and releases the claim, so a crashed worker cannot turn a
broken response into a fact. Three regression tests pin this policy
(`test_bootstrap_contract_violation_runs_conclude`,
`test_bootstrap_crash_does_not_run_conclude`,
`test_explore_crash_does_not_run_conclude`).

## Requirements

| ID | Test | Result |
|---|---|---|
| C-01 | Bootstrap selected only with a compatible worker or reserved intent | PASS |
| C-02 | Execute writes one Fact then completes the goal; replay writes nothing | PASS |
| C-03 | Execute timeout → conclude Fact; goal open; reason later eligible | PASS |
| C-04 | Conclude returning Complete is rejected; goal stays open | PASS |
| C-05 | Both stages fail → reservation released; no Fact/Complete | PASS |
| C-06 | Reason `complete` + `intents` rejected with no mutation | PASS |
| C-07 | Nonexistent fact ID rejected; no intent/completion written | PASS |
| C-08 | Empty reason with no open intents rejected | PASS |
| C-09 | Intents bounded to `max_intents`; truncation recorded | PASS |
| C-10 | Two concurrent reason attempts: exactly one lease | PASS |
| C-11 | Failed reason records a checkpoint, so no immediate retry | PASS |
| C-12 | Fact or hint growth makes one reason trigger eligible | PASS |
| C-13 | Open intents positive → zero makes reason eligible | PASS |
| C-14 | Explore receives exactly one intent and one lease | PASS |
| C-15 | Valid explore writes exactly one linked conclusion Fact | PASS |
| C-16 | Malformed explore then conclude writes one Fact (same task) | PASS |
| C-17 | Cancellation/lease loss blocks conclude; no Fact | PASS |
| C-18 | Job has no credentials/token; direct worker graph write raises | PASS |
| C-19 | Stopped engagement: no new work, task cancelled, late result rejected | PASS |
| C-20 | Full/unhealthy workers skipped; scheduler waits or picks another | PASS |
| C-21 | Two dispatchers: only one obtains leadership | PASS |
| C-22 | Extra fields rejected; legacy singular alias opt-in only | PASS |

## Transport, endpoint and scheduling tests

| Area | Test | Result |
|---|---|---|
| Typed methods round-trip over stdio JSON-RPC | `test_bridge_sends_typed_task_methods_and_returns_the_result` | PASS |
| Read timeout is `TimeoutError` (conclude-eligible) | `test_bridge_timeout_is_a_timeout_error` | PASS |
| Non-object worker reply is `ProtocolError` | `test_bridge_rejects_a_non_object_result` | PASS |
| Exact envelope, unknown keys, schema version, task type | `test_task_request_requires_the_exact_envelope` | PASS |
| Payload size cap | `test_task_request_is_bounded` | PASS |
| Executor runs once; crash becomes `accepted=false` | `test_endpoint_runs_the_configured_executor_once`, `test_endpoint_turns_a_crashed_executor_into_a_rejected_result` | PASS |
| No executor → explicit rejection | `test_endpoint_without_an_executor_rejects_instead_of_answering` | PASS |
| Scheduled tick dispatches when `on`, no-ops when `off` | `test_control_plane_tick_runs_bootstrap_and_honours_off` | PASS |

## Known limits

- The tick dispatches synchronously: one engagement with a 120 s task timeout
  can occupy a beat worker for that long. `max_engagements` is bounded and the
  Celery task has a 240 s soft limit; horizontal scaling is still one
  dispatcher per engagement by lease.
- The commit guard is a pre-commit check, not a distributed transaction. The
  dispatcher is the only writer and cancellation sets the task status first,
  but an operator cancellation that lands between the check and the graph write
  is not serialized against it.
- The task executor is deployment-supplied (`ARGUS_TASK_EXECUTOR=module:callable`)
  for the stdio worker, or `ARGUS_INTEGRATED_TASK_AGENTS=module:factory` for the
  in-process integrated runner. The integrated path (`agent/delegation/integration.py`,
  `control_plane/integrated.py`) runs intent → Task → Subtasks → Refiner →
  Reporter and returns one conclusion; the eight Stage 4 scenarios pass with
  deterministic agents (`integrated-e2e-results.md`). This slice still does not
  ship a live LLM-backed executor.
- On cancellation the task record is cancelled and late output is rejected; the
  beat tick does not yet kill a worker process that is mid-call. The bridge
  terminates its process on timeout or transport failure.
