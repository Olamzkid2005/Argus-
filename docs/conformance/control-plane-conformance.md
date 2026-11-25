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

**Result:** **25 passed, 0 skipped** (2026-11-25).

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
- Workers receive only a bounded JSON job. It contains no claim token, no
  database URL and no write authority.

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

## Known limits

- Worker runner is an injected protocol; the MCP `task_*` transport and live
  worker process adapter are not wired yet (Stage 4 integration).
- The dispatcher loop is exercised directly; Celery scheduling of
  `tick`/reconciliation is not part of this slice.
- On cancellation the worker process itself must be terminated by the runner
  adapter; this slice cancels the task record and rejects late output.
