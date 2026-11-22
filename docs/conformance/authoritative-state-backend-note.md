# Authoritative state backend plan — ARTEX first-pass decision

**Updated:** 22 November 2026  
**Status:** First ARTEX write path committed; integration verification blocked by environment, not by implementation.

## 1. What is done now

For the first ARTEX implementation pass, the repository now contains a
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

## 2. Current verification reality

The new graph tests are **correct but not verifiable here**, because the test
envionment has no reachable PostgreSQL. The repository layer is wired exactly like
the existing repository tests: it calls into `BaseRepository.db_operation`, which
calls `get_db().get_connection()`, which needs a real `DATABASE_URL`.

In this environment the failure is:

- `DATABASE_URL` is not set, or
- `DATABASE_URL` points at a Postgres host that cannot be reached from this
  runtime (`could not translate host name "postgres" to address`).

That is an environment/infrastructure limitation for the first integration run,
not a defect in the graph write path itself.

## 3. What that means for the requirements

- **C-18** is still `NOT VERIFIED`. The dispatcher-owned surface now exists, but
  the boundary is not yet proven end to end in a live run.
- **A-04** is `NOT VERIFIED`. The migration, repository, dispatcher surface, and
  unit tests are committed; the integration verification is blocked by the missing
  PostgreSQL connection.
- The conformance notes now record this as a **blocked verification state**, not
  as a completed implementation.

## 4. How to finish verification

To move A-04 out of `NOT VERIFIED`, run the graph tests against a reachable
PostgreSQL database with the migration applied, for example:

- a real service-backed Postgres available to this environment, or
- a local/CI Postgres whose connection string is supplied through
  `TEST_DATABASE_URL` or `DATABASE_URL`, matching how other repository tests in
  this repo are run.

The shortest verification is:

1. provide a reachable `DATABASE_URL`,
2. apply `database/migrations/033_graph_tables.sql` (or let
   `run_migrations()` apply pending migrations),
3. run `tests/test_graph_repository.py`,
4. confirm the asset upsert, node creation, anchor attach, and anchor readback
   tests pass.

## 5. What is still open after this note

- A reachable PostgreSQL connection for the first integration verification.
- Stage 1 CAIRN control-plane alignment: leases/claims/worker selection/cancellation
  on top of this dispatcher-owned graph repository.
- TUI/SQLite parity, if a later conformance requirement demands it.
- Expansion from the A-04 slice to the rest of the ARTEX layer
  (coverage, planner frontier, planner todos, graph outbox, graph-change-driven
  planning).

## 6. Definitions used

- **Authoritative backend:** the one storage system that owns durable state for
  the_first_implementation_pass.
- **First implementation pass:** the smallest ARTEX cut that can be tested against
  a real repository call path, not the full final architecture.
- **Dispatcher-owned:** mutations are submitted to dispatcher methods; workers do
  not commit graph state directly.
- **Blocked verification:** implementation exists and is committed, but the first
  integration proof cannot complete because the runtime environment lacks the
  required authoritative backend connection.
