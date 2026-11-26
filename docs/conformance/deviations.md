# Deviations and open gate items — Stage 4 (fact-and-intent real boundary)

**Date:** 26 November 2026
**Plan ref:** `docs/conformance/argus_three_frameworks_implementation_conformance_plan.md` §7.3
(deviation rules), §7.5 (integration scenarios), §7.6 (this artefact)
**Companion ledger:** `fact-and-intent-conformance.md`

A deviation here is an intentional adaptation recorded with its reason — never silent parity. Open
gate items are requirements that cannot be performed in this environment and are not claimed
anywhere as passes.

---

## 1. Open gate items (NOT RUN — not claimed as passes)

1. **Live-lab network target.** No authorized lab target exists in this environment, so no live
   network tool run was performed. All real tool executions are hermetic (`nuclei -version`, local
   `eslint` on a fixture, `/bin/sleep`) or gate refusals. §7.5 scenario wording that assumes "an
   authorized lab" is satisfied here only up to the hermetic boundary; the live-network remainder
   is explicitly NOT RUN.
2. **Live LLM for Generator/Reasoner/Bootstrapper.** No LLM credentials are configured, so the
   intent-generating roles remain test doubles sitting above the real executor. Single-generator
   enforcement is proven structurally (flag ownership: fact-intent `on` forces planner-loop defer;
   shared normalized-objective cross-dedupe in `apply_reason`), not by racing two live planners.
3. **>90 s wall-clock lease renewal.** Renewal is proven with a 2-second explore lease outlasted by
   heartbeated work (`test_heartbeat_renews_claim_across_long_task`), plus the lapse-without-renewal
   path (`test_expired_claim_rejects_late_conclusion`). The production default claim lease is 90 s,
   but a continuous >90 s renewal run was not executed in this pass.
4. **`semgrep` / `bandit` on the real path.** The parsers exist and are unit-tested, but the binaries
   cannot execute under the `ToolRunner` locked environment on this host: the venv-3.11
   `PYTHONPATH` pin breaks the Homebrew `python3.14` shims (`SRE module mismatch`). Real-path
   evidence therefore covers `nuclei`, `eslint` and `sleep` only.
5. **No in-flight heartbeat on the stdio `task_*` bridge.** Renewal is a dispatcher-owned closure
   passed only to executors advertising heartbeat support. A long stdio explore that outlasts its
   lease lapses and relies on the crash/reconcile path (`test_crash_self_heals…`) instead of renewal.
   This is documented behavior, not a regression.

## 2. Recorded deviations (intentional adaptations)

1. **Approval gate shape.** There is no upstream reference implementation for the approval check, so
   the rule is Argus-defined and recorded here: tools in `HIGH_IMPACT_TOOLS`
   (`agent/delegation/tool_executor.py`) require `arguments.approval.by` (non-blank); a lone
   informational argv (`-version` / `-h` with no target) is exempt because it changes nothing.
   Refusals are recorded on the real adapter with outcome `refused`, `check: approval`.
2. **Cache discipline for tool results.** `ToolRunner` caches only `_cacheable` results (exit 0 or
   known findings-exit-codes); killed/failed results are never replayed. `RealToolExecutor` accepts
   `arguments.cache_mode` (`NORMAL` default, `NO_CACHE` for probes like the cancel test that must
   observe a live process). This deviates from "cache everything" in that correctness-critical
   probes bypass the cache by design.
3. **Claim-lost mid-run maps to `cancelled`.** A `GraphClaimLostError` surfacing while a worker call
   is in flight fails the Exploration task and returns `"cancelled"` from `run_explore`, with no
   graph write — the same observable outcome as an operator cancel. Rationale: from the engagement's
   point of view a lost lease and a cancel both mean "this attempt must not conclude."
4. **Findings land `PENDING` and never prove goals alone.** Tool-derived findings persist with
   `PENDING` status plus delegation provenance; `prove_goal_from_findings` with an unverified
   finding raises `GraphMutationError` (A-08 gate). A separate verifier-backed promotion step is
   required before any goal can close — that promotion flow is outside this pass.
5. **Reason-job overview is dispatcher-computed, not worker-computed.** The §5.2B overview (assets,
   anchors, coverage, open/todo/scheduled state) is assembled by the dispatcher into the reason
   job; workers never compute it. This keeps graph reads inside the lease-holding dispatcher.

## 3. Baseline / environment notes (not deviations)

- `make test-v5` (Bun, `Argus-Tui/packages/opencode`) is slow in this sandbox (~2–3 s per CLI-spawn
  test; full suite >10 min) and contains environment-sensitive tests that shell out to `python3`.
  No TypeScript file changed in this pass, so `test-v5` outcomes are independent of it; any failure
  is checked against the pre-existing baseline, never attributed to this work. Final counts and
  exit code are recorded in `fact-and-intent-conformance.md` §6.
- `ruff` is not installed in the `argus-workers/venv` used here, so the §7.4 `ruff check .` step
  could not run; `git diff --check` is clean and the changed files were already lint-clean in the
  prior pass.
- The tool-result cache is inert in this checkout for the exercised paths (no `cache:tool_result:*`
  keys in Redis outside the single poisoned `sleep` entry found and removed during diagnosis); there
  is no Redis server dependency for the Python suites beyond the existing test fixtures.
