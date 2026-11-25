# Authoritative state backend plan — graph first-pass decision

**Updated:** 23 November 2026  
**Status:** First graph write path reviewed and repaired; integration verification still blocked by the missing PostgreSQL, not by implementation.

## 1. What is done now

For the first graph implementation pass, the repository now contains a
dispatcher-owned graph write path:

- `argus-workers/database/migrations/033_graph_tables.sql` — canonical asset
  identity, exploration nodes, and explicit anchors.
- `argus-workers/database/graph_repository.py` — dispatcher-owned canonical graph
  repository using the existing `BaseRepository` connection discipline.
- `argus-workers/database/dispatcher_graph.py` — smallest dispatcher surface that
  owns the first durable write.
- `argus-workers/tests/test_graph_repository.py` — asset + node + anchor
  verification tests.
- `argus-workers/database/repositories/base.py` — table allowlist updated for the
  new graph tables.
- `docs/conformance/` notes updated to record the current state.

This is the smallest A-04 slice that still exercises the C-18 boundary: asset
upsert, exploration node creation, and anchor creation/readback all flow through
the dispatcher-owned repository surface.

## 1a. Review pass (23 November 2026) — defects found and fixed

A line-by-line review of the first pass found real defects that the skip-marked
tests could not catch, all now fixed:

1. **Migration could not be applied at all.** `graph_anchor_scopes.anchor_id`
   referenced `graph_anchors(node_id)`, which is not unique on its own, so
   PostgreSQL rejects the foreign key. `graph_anchors` now has a surrogate `id`
   primary key (with `UNIQUE (node_id, asset_id, role)` retained) and anchor
   scopes reference that. `asset_coverage_for_scope` joins on it too, instead of
   conflating `anchor_id` with `node_id`.
2. **Every JSONB write would have raised `can't adapt type 'dict'`.**
   `upsert_asset(metadata=...)`, `create_node(payload=...)`,
   `create_todo(payload=..., frontier_position=...)` and
   `enqueue_outbox(payload=...)` passed raw dicts; psycopg2 has no dict adapter
   in this project (every other repository wraps in `psycopg2.extras.Json`).
   All four now use `Json(...)`.
3. **`find_frontier_for_engagement` was ambiguous SQL.** It filters
   `engagement_id`/`state` across a join of `planner_frontier` and
   `graph_nodes`, both of which have those columns, so PostgreSQL would reject
   it. Predicates are now qualified with `pf.`.
4. **Coverage could regress.** Re-attaching an anchor scope with the default
   `pending` overwrote an established `incorporated`/`covered` state, and
   `incorporated_at` was never stamped. Re-attach no longer downgrades, and the
   first real coverage transition stamps `incorporated_at`.
5. **Outbox was unusable with default arguments.** `scope_id` is a `UUID NOT NULL`
   column but `enqueue_outbox`/`dequeue_outbox`/`find_outbox_for_scope` defaulted
   it to `""`, which is an invalid uuid. `scope_id` is now required on both the
   repository and dispatcher surfaces, with an explicit `GraphMutationError`.
6. **Exploration edges could cross engagements.** `attach_edge` wrote any
   source/target pair under a caller-supplied `engagement_id`, letting one
   engagement's graph link into another's. Both endpoints are now verified to
   belong to that engagement.
7. **Migration transaction handling.** The file carried its own
   `BEGIN`/`COMMIT`, which ends the migration runner's per-migration transaction
   early and can leave a half-applied migration. It now leaves transaction
   control to the runner, matching the other migrations.
8. **Asset upsert lost scope on conflict, and `update_by_id` had no allowlist**
   for `graph_nodes`. Scope is now preserved via `COALESCE(EXCLUDED.scope_id, …)`,
   and `graph_nodes` has a mutable-column allowlist for the schema-introspection
   fallback path.

## 2. Current verification reality

The new graph tests are **correct but not verifiable here**, because the test
environment has no reachable PostgreSQL (and this runtime cannot install one: no
root, no `postgres`/`initdb`). The repository layer is wired exactly like
the existing repository tests: it calls into `BaseRepository.db_operation`, which
calls `get_db().get_connection()`, which needs a real `DATABASE_URL`.

In this environment the failure is:

- `DATABASE_URL` is not set, or
- `DATABASE_URL` points at a Postgres host that cannot be reached from this
  runtime (`could not translate host name "postgres" to address`).

That is an environment/infrastructure limitation for the first integration run,
not a defect in the graph write path itself.

## 3. What that means for the requirements

Superseded by the DB-backed run below: A-04 and the six graph surfaces are now
verified against a real PostgreSQL, and C-18 is partially verified.

- **A-04** is `VERIFIED (DB-BACKED)`.
- **Anchors/coverage, per-engagement exploration graph, frontier, todos,
  outbox** are `VERIFIED (DB-BACKED)`.
- **Graph-change-driven planning** is `PARTIALLY VERIFIED (DB-BACKED)`: the
  durable flow up to the outbox is exercised, but no automatic
  mutation-triggered planning pass exists yet.
- **C-18** is `PARTIALLY VERIFIED`: every verified graph write goes through
  `DispatcherGraph`, but the "workers never import the repository" rule is
  still enforced by convention and review, not by an import boundary.

## 3a. DB-backed verification (23 November 2026)

The blocking condition above was resolved by running the tests against a real
PostgreSQL 16 instance (`pgserver` bundled binaries) with
`database/migrations/033_graph_tables.sql` applied directly:

```
46 passed, 0 skipped
```

That run surfaced four failures that the skip path had hidden, all now fixed:

1. `asset_coverage_for_scope` ordered `s.created_at DESC`, so anchors from other
   scopes (NULL coverage) sorted ahead of the requested scope's row. Changed to
   `DESC NULLS LAST`.
2. `enqueue_outbox` tests passed non-UUID strings (`node-1`, `eng-1`) into UUID
   columns; the test now uses real UUIDs.
3. Two tests compared a Postgres-canonical dashed UUID against a 32-char hex
   input; they now build the engagement id as `str(uuid.uuid4())`.
4. Two tests anchored to the globally deduplicated canonical asset
   `api.example.com/endpoint`, so anchors from other tests leaked into their
   result sets. They now use their own asset identities.

## 4. How to run the verification

CI now does this automatically: the `graph-repository-db` job in
`.github/workflows/lint.yml` starts a `postgres:16` service, applies migration
033, runs `tests/test_graph_repository.py`, and fails if any test is skipped.

To reproduce locally:

1. provide a reachable `DATABASE_URL`,
2. apply `database/migrations/033_graph_tables.sql` (or let
   `run_migrations()` apply pending migrations),
3. run `python -m pytest tests/test_graph_repository.py`,
4. confirm 0 tests are skipped.

## 5. What is implemented and committed now

For the first graph implementation pass, the repository now contains a
dispatcher-owned graph write path that covers all of the listed graph
components:

- canonical assets and explicit anchors (`graph_assets`, `graph_nodes`,
  `graph_anchors`)
- engagement-scoped anchors and coverage metadata (`graph_anchor_scopes`,
  `asset_coverage_for_scope`, `attach_anchor_scope`, `update_anchor_coverage`)
- per-engagement exploration edges (`graph_node_edges`,
  `attach_edge`, `find_edges_for_engagement`, `find_edges_for_node`)
- recoverable planner frontier (`planner_frontier`,
  `set_frontier_node`, `remove_frontier_node`, `find_frontier_for_engagement`,
  `clear_frontier_for_engagement`)
- persistent planner todos (`planner_todos`, `create_todo`,
  `update_todo_status`, `find_todos_for_engagement`,
  `find_open_todos_for_engagement`)
- graph outbox (`graph_outbox`, `enqueue_outbox`, `dequeue_outbox`,
  `find_outbox_for_scope`, `record_outbox_error`, `requeue_outbox`)
- dispatcher-owned surface for all of the above
  (`DispatcherGraph`, `GraphMutationError`)

All of those surfaces are committed through the existing
`argus-workers/database` repository/connection discipline, and the
`BaseRepository` table allowlist has been extended for the new graph tables.

The unit tests for these surfaces exist and the pure-logic dispatcher
validation tests pass in this environment. The repository integration tests
are skipped here because `DATABASE_URL` is not reachable.

The conformance notes now treat the full graph first-pass surface as
**implemented and committed**, and **verification as blocked by
environment**, not as incomplete.

## 6. A2 ingestion, coverage and enforced C-18 (23 November 2026)

A2 is implemented on top of the graph tables:

- `database/graph_identity.py` — deterministic canonicalizers for `root_domain`,
  `subdomain`, `ip`, `service`, `app` and `endpoint`: Unicode NFKC/IDNA hosts,
  lower case, no trailing dot, default-port stripping, userinfo removal,
  trailing-slash normalization, compressed IP form and `protocol://host:port`
  service identity. Parent chains are computed here (`endpoint -> subdomain ->
  root_domain`, `ip/service -> ip`). Authorized-scope matching mirrors
  `tools/scope_validator.py`: an exact host, or `*.domain` matching exactly one
  label, plus CIDR `ipRanges`; an empty scope is fail-closed.
- `database/graph_ingest.py` — the only path from raw observations to canonical
  assets. It canonicalizes, enforces scope, links parents, upserts the asset and
  merges the observation. Out-of-scope discoveries are stored as rejected
  observations (`accepted = false`, `rejection_reason = out_of_scope`) and never
  become schedulable assets.
- `tasks/graph_ingestion.py` — the recon bridge. `run_recon`/`expand_recon` call
  `ingest_recon_result` after the recon pipeline, so real `ReconContext`
  outcomes (target URL, live endpoints, subdomains, open ports, crawled/API/auth
  URLs) become observations and assets through the dispatcher. Ingestion is
  best-effort: a bad or out-of-scope value is counted and logged, never raised
  into the recon task.
- IPv6 service identities are bracketed (`tcp://[2001:db8::1]:443`), because an
  unbracketed IPv6 address is ambiguous with `host:port`. Scope checks resolve
  the host with a URL parse (brackets stripped) and still accept legacy
  unbracketed keys.
- `database/migrations/034_graph_asset_observations.sql` —
  `graph_asset_observations`, self-referencing parent columns on `graph_assets`,
  and a scope-aware unique identity index. The 033 global
  `(canonical_key, asset_type)` constraint is replaced by
  `(COALESCE(scope_id, ...), canonical_key, asset_type)`, so the same domain in
  two scopes stays two assets (A-03) while unscoped assets keep one shared
  bucket.
- Coverage: `compute_scope_coverage(scope_id, authorized_scope=...)` reports
  discovered assets per type, covered vs untested, in-scope vs out-of-scope, and
  `untested_asset_types` / `undiscovered_asset_types`.
  `asset_coverage_for_scope` now also reports `in_scope` and `untested`.

- Tenant boundary (A-03): `database/migrations/035_graph_tenant_boundary.sql`
  adds `tenant_id` (the engagement's `org_id`) to `graph_assets` and
  `graph_asset_observations`. `DispatcherGraph` resolves the scope owner and
  raises `GraphTenantViolation` when a write names another tenant; the repository
  repeats the check at the row level, so a mismatched asset or observation write
  is rejected rather than silently written or re-owned.
- Computed coverage (A2): `DispatcherGraph.coverage_report(scope_id)` loads
  `engagements.authorized_scope` and compares it with the assets actually
  discovered in that scope. It reports `approved_but_undiscovered` gaps
  (domains and CIDR `ipRanges`), `discovered_but_unapproved` assets,
  `rejected_observations` with their count, and the untested/undiscovered asset
  classes. `argus graph-coverage -e <engagement>` exposes the same report; both
  paths are read-only over the graph tables.
- Coverage-driven planning (A2): `schedule_coverage_gaps(engagement_id)` turns
  each approved-but-undiscovered target into an `expand` planner todo and each
  asset class with untested discoveries into a `verify` todo, and puts both on
  the recoverable `planner_frontier` with a `coverage_gap:<gap key>` reason. It
  is idempotent per `coverage_gap_key`, so repeated recon passes do not
  duplicate work. The recon bridge calls it after every ingestion pass, and
  `argus graph-coverage --schedule` runs it on demand.
- Coverage-gap execution loop (A2): `claim_recon_todo` selects the next gap from
  the frontiers/todo queue (highest frontier priority, then oldest), leases it
  with an owner and `started_at` (expired leases are reclaimable) and marks its
  frontier node running. `tasks.graph_planner.dispatch_next_coverage_gap` derives
  recon targets — `https://<host>` for an approved domain, the CIDR unchanged for
  an approved range, and the discovered assets of an untested class — then sends
  `tasks.recon.expand_recon` with the gap's todo id. The recon task's graph
  ingestion hook calls `complete_recon_todo`: the ingested assets (plus the
  class's discovered assets) are anchored to the node and marked `covered`, the
  todo reaches `done`, its node concludes and its frontier row is deleted. A
  dispatch failure releases the claim back to `open`. Selection is scoped by
  engagement, so a gap scheduled for one engagement is never claimed or
  dispatched for another.

C-18 is now enforced twice:

- Runtime: every mutating repository method calls
  `require_graph_write_owner`; only `dispatcher_write_scope`, opened by
  `DispatcherGraph`'s `@dispatcher_owned` methods, satisfies it. Direct
  repository writes, including through `GraphIngestor`, raise
  `GraphOwnershipError`.
- Static: `scripts/check_graph_import_boundary.py` fails CI when a module outside
  the dispatcher-owned allowlist imports `graph_repository`, `dispatcher_graph`
  or `graph_ingest`.

Verification: the `graph-repository-db` CI job runs the full migration runner
through 037 against Postgres 16 (and asserts the scoped identity index, both
`tenant_id` columns, the claim/turn columns and the intent claim index), runs
the import-boundary check and runs the graph tests. Locally the same steps give
**121 passed, 0 skipped, 38 migrations applied**. The DB-backed suites include
two-tool merges across case, default port, trailing slash, IDNA/punycode hosts
and differently shaped service keys (`TestCrossToolMerge`), computed coverage
gaps plus rejected out-of-scope discoveries (`TestComputedCoverage`), coverage
gaps becoming frontier/todo work (`TestCoverageDrivenPlanning`), the claimed →
dispatched → ingested → closed gap loop for an approved domain, CIDR and untested
asset class (`TestCoverageGapReconLoop`), and cross-tenant asset/observation
rejection (`TestTenantBoundary`).

## 6.1 Production planner loop, worker protocol and rollout flags (A3–A5)

- **The loop runs in production.** `tasks.graph_planner.drain_planner_outbox` is
  registered as the Celery beat entry `drain-planner-outbox` (every 15 s) and
  scans `graph_outbox` for engagements with queued wakes, then runs bounded
  turns for each. `tasks.graph_planner.run_planner_loop` is also registered for
  an optional immediate wake (`ARGUS_PLANNER_WAKE_DISPATCH=1`); the beat drain is
  the floor, so a missed wake is never stranded. Verified against a fresh
  PostgreSQL database through 037 by invoking the registered task itself
  (`drain_planner_outbox_task.apply`): a committed burst of 3 queued rows became
  3 dequeued rows linked to one completed turn (`events_consumed=3`,
  `intents_created=2`), a second drain reported 0 turns/0 engagements and left
  the graph unchanged, and two concurrent drains consumed 4/4 committed rows
  with one turn and exactly 3 intents (no loss, no double-apply).
- **Goal proof is verifier-backed (A-08).** `prove_goal_from_findings` only
  accepts findings that belong to the engagement, are `CONFIRMED`/`VERIFIED` in
  the existing `findings` table, **and** carry verifier provenance in their
  `evidence` JSONB (`verifier_provenance_error`): a `proof_status` of
  `reproduced` with captured evidence/control refs, a `verification` result with
  `verified: true` and no verifier error, or a `verification_status` of
  `CONFIRMED` next to the artifacts the verifier captured. A status column, a
  scanner's self-reported `verified` flag, an analyst feedback verdict or an
  error-log-only artifact is a claim, not proof, and rejects the whole proof
  before any write. On success it writes the graph finding node, a `proves` edge
  and the goal conclusion in one dispatcher transaction.
- **The verifier concludes the goal itself (A-08).** The finding persistence
  service calls the proof hook (`orchestrator_pkg/persistence/goal_proof.py`,
  registered in the graph-write allowlist next to the other delegators) after a save,
  so a finding that reaches `CONFIRMED` through the real verification pipeline
  concludes the goal it proves without an explicit dispatcher call. Attribution
  is explicit (`goal_node_id`/`proves_goal_ids` on the finding or its evidence,
  carried through the verification agent); a single-objective engagement
  attributes to its one open goal, and with several open goals an unattributed
  finding proves none — a reproduced information leak must not conclude an RCE
  objective. A rejected or unreachable graph never fails the scan: the rows are
  already written and the rejection is logged.
- **Provenance and verdict reach the row (A-08).** The rule above only means
  something if the pipeline actually stores what the verifier established, so
  `promote_finding`'s output is folded into `findings.evidence` on the way to the
  database (`tools.verification.proof_status.evidence_with_proof`, applied by
  the orchestrator persistence service, the verification agent and local mode)
  and the promoted verdict is written to the `status` column by both the
  PostgreSQL and SQLite repositories. Re-reporting a finding never downgrades an
  existing `CONFIRMED`/`VERIFIED` row, so a later unverified scan cannot erase
  the proof a goal rests on.
- **Rejected writes are audited (A-05).** Cross-engagement edges, unknown
  endpoints and out-of-scope intent anchors raise `GraphMutationError` and are
  recorded in `graph_write_rejections` with the operation and reason.
- **Worker protocol and isolation (A4).** `claim_intent_node` gives a worker at
  most one live intent, with a random fencing token and a 90-second
  database-clock lease; `heartbeat_intent_node` renews it and
  `complete_intent_node` writes exactly one conclusion fact plus a `yields` edge,
  rejecting stale tokens with `GraphClaimLostError`. The MCP transport exposes
  `graph_claim_intent`, `graph_heartbeat_intent`, `graph_complete_intent`,
  `graph_report_trace`, `graph_search_traces` and `graph_record_action` through
  the allow-listed `database/graph_worker_rpc.py` facade.
- **Trace reuse (A-13).** `graph_traces` stores redacted, engagement-scoped
  summaries; `worker_intent_package` includes the intent, anchored assets,
  prerequisite facts and recent traces, all marked `trust: untrusted` and bounded
  by `sanitize_untrusted_text`, so a worker reuses another's observation without
  repeating it or following it as an instruction (A-14).
- **Idempotent results (A-16).** `graph_actions` is unique on
  `(engagement_id, action_id)`; replaying an action returns the originally
  committed result instead of a second logical update.
- **Rollout flags (A5).** `orchestrator_pkg/planning/flags.py` implements
  `ARGUS_ORCHESTRATION_V2`, `ARGUS_GRAPH_EXPLORATION`,
  `ARGUS_HIERARCHICAL_DELEGATION` and `ARGUS_FACT_INTENT_PROTOCOL` with
  `off|shadow|on`; typos raise. `ARGUS_ORCHESTRATION_V2` is the master switch:
  `off` rolls back, `shadow` keeps the loop non-mutating, and only `on` lets
  `ARGUS_GRAPH_EXPLORATION` choose live vs shadow. On the real drain path,
  shadow left nodes/edges/anchors/intents/conclusions unchanged (0 writes)
  while recording one turn and consuming the burst; `off` wrote nothing and
  left the rows queued; flipping back to `on` consumed the same queued rows
  without any data repair.
- **The deployment turns the loop on (A5).** The unset fallback in `flags.py`
  stays `off` because it is the per-process rollback switch, but the shipped
  deployment configuration — `docker-compose.yml` (worker and `celery-beat`),
  `.env.example` and `start-argus.sh` — sets `ARGUS_ORCHESTRATION_V2=on` and
  `ARGUS_GRAPH_EXPLORATION=on`, so the registered 15-second drain actually does
  work in a normal deployment instead of being a permanent no-op. A disabled
  drain logs the resolved flag values and the variables to set, and
  `mode_report()` exposes the same resolution for support. Shadow remains the
  documented first step for an existing deployment.

## 7. What is still open after this note

- Fact-and-intent protocol work proper: typed `bootstrap`/`reason`/`explore` result
  contracts, reason lease/checkpoint scheduling, worker registry and single
  dispatcher leader election (C-01…C-22 apart from the ownership/lease pieces
  above).
- PentAGI hierarchical delegation: P-01…P-17 pass against PostgreSQL and are
  recorded in `pentagi-delegation-conformance.md`. What remains is integration,
  not the workstream contract: the production dispatcher does not yet create a
  task for each claimed intent, the MCP `task_*` bridge endpoints are not added,
  and no live-model Generator/Refiner/specialist run has been made (Stage 4).
- A5 activation: the deployment now runs the loop with
  `ARGUS_ORCHESTRATION_V2=on`/`ARGUS_GRAPH_EXPLORATION=on` by default, so the
  remaining gate is operational rather than code: compare shadow turns against
  the deterministic coverage scheduler on a real assessment and keep the
  documented `off` rollback path exercised.
- TUI/SQLite parity, if a later conformance requirement demands it.

## 8. Definitions used

- **Authoritative backend:** the one storage system that owns durable state for
  the_first_implementation_pass.
- **First implementation pass:** the smallest graph cut that can be tested against
  a real repository call path, not the full final architecture.
- **Dispatcher-owned:** mutations are submitted to dispatcher methods; workers do
  not commit graph state directly.
- **Blocked verification:** implementation exists and is committed, but the first
  integration proof cannot complete because the runtime environment lacks the
  required authoritative backend connection.
