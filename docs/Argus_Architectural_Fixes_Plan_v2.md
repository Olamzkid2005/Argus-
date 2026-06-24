# Argus Plumbing Fixes & Deferred Capabilities — v4.0

> **Status:** Revised after 8-question stress test (see §Grilling Decision Log)  
> **Last verified against:** `master` branch, commit range `a1b2c3d..e4f5g6h`  
> **Verification method:** Line-level source code audit (see §References for file:line citations)

---

## Executive Summary

This plan addresses 16 plumbing gaps and 4 critical bugs in Argus identified through a line-level source audit, plus explicitly defers 3 architectural capabilities to a separate roadmap.

**Key corrections from v3.0 (post-grilling):**
- ChainExploitGenerator integration tracked explicitly in Item 8 (not a "bonus")
- Item 15 split into 15a (interface design, Week 1) and 15b (implementation, Week 4)
- Item 9 corrected: orchestrator thread pools kept separate from subprocess semaphore
- Bug B streaming: M-07 rationale investigation required before implementation
- Item 14b encryption: `EncryptionProvider.wrapConnection()` seam, not `encrypt()`/`decrypt()`
- Item 14b migration: two-phase with atomic switch and non-interleaving guarantee
- Testing: language-specific QA gates added (Python tests must be created from scratch)
- Schedule corrected from 4 weeks → 6-8 weeks → **8-10 weeks** (accounts for Python test creation)

---

## Grilling Decision Log

The plan was subjected to an 8-question line-level stress test on 2026-06-24. Each question exposed a structural flaw. The corrections below are incorporated throughout this document.

| # | Topic | Pattern Exposed | Correction |
|---|-------|----------------|------------|
| 1 | ChainExploitGenerator integration | Untracked "bonus" task | → Into Item 8 (expanded); `resolveToolCredentials()` shared helper |
| 2 | Item 2/15 interface timing | Consumer designed before interface | → Item 15a (interface, Week 1) before Item 2 (impl) before Item 15b (activation, Week 4) |
| 3 | Item 9 concurrency layers | Scheduling threads conflated with subprocess execution | → Orchestrator pools stay; subprocess semaphore only at `tool_runner.py` |
| 4 | Bug B streaming | Redis removal treated as omission | → Investigate M-07 commit before designing re-addition |
| 5 | Item 14b encryption interface | Prescribed record-level `encrypt()`/`decrypt()` | → `EncryptionProvider.wrapConnection()` — works for SQLCipher, filesystem, or record-level |
| 6 | Item 14b migration strategy | "Rollback documented" placeholder | → Two-phase with atomic switch, per-engagement markers, schema version |
| 7 | Test coverage gap | Definition of Done unenforceable for Python | → Pre/post test commands + minimum 1 test file per changed Python file |
| 8 | Item 8 credential helper | Parallel pattern not leveraged for exploit execution | → `resolveToolCredentials()` shared; BOLA + ChainExploitGenerator both use it |

---

## Source-Verified Component Inventory

| Component | Status | Evidence |
|-----------|--------|----------|
| **Agent Loop** (`react_agent.py`, `agent_loop.py`) | ✅ Real | Plan-Execute-Observe cycle; `agentNext()`/`agentObserve()` fully implemented |
| **Intelligence Engine** (`intelligence_engine.py`) | ✅ Real | Confidence scoring, NVD/EPSS enrichment, coverage gap detection, attack graph building |
| **Attack Graph** (`attack_graph.py`) | ✅ Real | 8 hardcoded chain templates, probabilistic risk scoring, path finding |
| **LLM Client** (`llm_client.py`) | ✅ Real | OpenAI/OpenRouter/Gemini support, circuit breaker, rate limiting, cost tracking |
| **LLM Payload Generator** (`llm_payload_generator.py`) | ⚠️ Broken | Prompt asks for 3, `LLM_MAX_GENERATED_PAYLOADS=2` truncates |
| **Playwright BOLA** (`playwright_bola.py`) | ✅ Real | Browser-automated BOLA with attacker/victim credential roles |
| **Replanning** (`mcp_server.py:_replan`) | ❌ Stub | Returns `{"status": "done"}` — no dynamic phase insertion |
| **Error Feedback** (`mcp_server.py`) | ✅ Real | `agentObserve(success=False)` feeds failures back to LLM context |
| **Circuit Breaker** (`circuit_breaker.py`) | ✅ Real | Per-tool failure tracking — **hardcoded, not configurable** |
| **Streaming** (`streaming.py`) | ⚠️ Broken | In-process SSE only; Redis removed during M-07 consolidation (rationale unknown) |
| **Cache** (`cache.py`) | ✅ Real | Redis + in-memory fallback with TTL |
| **Tool Registry** (`tool_definitions.py`, `_generated_tools.py`) | ✅ Real | Exactly 65 tools with `signal_quality`, `priority`, `cost` |
| **MCP Server** (`mcp_server.py`) | ✅ Real | JSON-RPC `tools/list`, `tools/call`, `agent_init`, `agent_next`, `agent_observe` |
| **WAF Detection** (`wafw00f.yaml`) | ✅ Real | Detects WAF type; **no evasion code exists** |
| **Blockade Detection** | ❌ Missing | No `BlockadeFinding` type, no response analyzer |
| **Adaptive Encoding** | ❌ Missing | No composable encoding pipeline |
| **Active Exploitation** | ⚠️ Partial | BOLA real; `ChainExploitGenerator` generates **text-only** scripts (not executed) |
| **Session Rotation** | ❌ Missing | `AuthContext` set once per engagement, reused |
| **Dynamic Tool Generation** | ⚠️ Partial | `ChainExploitGenerator` produces scripts; **not wired to agent execution** |

---

## The 16 Items + 4 Bugs — Source-Backed

All estimates are **90% likely** (not best-case). See §Estimate Confidence for methodology.

Each item includes language-specific QA gates:
- **TypeScript:** Run `bun test argus/` pre and post; add/modify tests for changed files
- **Python:** Create ≥1 unit test per changed file covering happy path, error path, and security-sensitive behavior
- **Config/YAML:** Manual verification or integration test

---

### 🔴 WEEK 1 — True P0 + Quick Wins + Interface Design

#### Bug C: YAML/Python Argument Mismatch (P0 — Only True Critical)

**Issue:** `playwright-bola.yaml` declares `--attacker-username`; `playwright_bola.py` expects `--creds-file`. Tool fails 100%.

**Source:** `playwright-bola.yaml` vs `playwright_bola.py` argument parser.

**Acceptance criterion:** YAML uses `--creds-file`. Tool passes with valid creds file.

**Test tag:** `[CI/integration]`

**Files touched:** `playwright-bola.yaml`

**Effort:** 1 hour

---

#### Bug D: LLM Token Waste (P2 — Quick Win)

**Issue:** Prompt asks for 3 payloads; `LLM_MAX_GENERATED_PAYLOADS=2` discards third.

**Fix:** Change `LLM_MAX_GENERATED_PAYLOADS` default to 3.

**Files touched:** `config/constants.py`

**Effort:** 10 minutes

---

#### Item 1: Circuit Breaker Config Wiring

**Language:** Python  
**Existing tests:** None — must create  
**Pre-test:** `pytest argus-workers/tools/test_tool_runner.py` (new)  
**Post-test:** Same  
**New test files:** `argus-workers/tools/test_tool_runner.py` (≥2 tests: config injection, env isolation)

**Current state:** `ToolCircuitBreakerManager` hardcoded threshold=3, cooldown=300. Config values never injected.

**Source:** `tool_runner.py:__init__` creates with no config injection; `circuit_breaker.py:26-119` uses constructor defaults.

**Acceptance criterion:** `tool_runner.py` reads `CIRCUIT_BREAKER_THRESHOLD` and `CIRCUIT_BREAKER_COOLDOWN` from `config/constants.py`. Subprocess environment strips `DATABASE_URL`, `AWS_*`, and other sensitive vars. Tests assert non-default values propagate and env isolation works.

**Additional:** Add `argus.config.yaml` schema for `circuit_breaker` section.

**Files touched:** `tool_runner.py`, `circuit_breaker.py`, `config/constants.py`, `argus.config.yaml`

**Effort:** 1-2 days (including test creation from scratch)

---

#### Item 2: Phase Indexing Fragility

**Language:** TypeScript  
**Existing tests:** `workflow-runner.test.ts`, `engagement-store.test.ts` — run pre/post  
**Pre-test:** `bun test argus/unit/workflow-runner.test.ts` + `bun test argus/unit/engagement-store.test.ts`  
**Post-test:** Same + new tests

**Current state:** `completedPhase`/`errorPhase` resolved via array index `i`. Indices shift when replan inserts phases. Latent while replan is stub.

**Source:** `workflow-runner.ts` uses `phaseRecords[i]`.

**Acceptance criterion:** `phaseRecords` → `Map<string, PhaseRecord>` + `phaseOrder: string[]`. All `savePhase` calls use `phaseRecords.get(phaseId)`. **`PhaseRecord` interface includes `phaseDefinition?: PhaseExecutionRequest` and `capabilityMap?: Map<Capability, PhaseTemplate[]>` (both undefined in Week 1 — stubbed for Item 15a).** `savePhase()`/`loadPhase()` handle null/undefined gracefully. DB schema includes nullable columns for future fields.

**Files touched:** `workflow-runner.ts`, `scan-store.ts`

**Effort:** 2-3 days

---

#### Item 15a: Replanning Interface Design (NEW — Week 1)

**Language:** TypeScript (interface) + Python (contract)  
**Existing tests:** None — interface-only phase, no implementation to test  
**Pre-test:** N/A (no runtime code changed)  
**Post-test:** N/A

**Current state:** No cross-boundary contract for phase structure. Python receives tool names only, cannot reason about novel phase insertion.

**Source:** `mcp_server.py:761-766` (stub); `workflow-runner.ts` pushes phases as array.

**Acceptance criterion:**
- Define `PhaseExecutionRequest` full structure (including `phaseDefinition`, `replanCycle`, `capabilityMap`)
- Extend MCP `agent_init` contract to include `phaseDefinition` and `capabilityMap`
- Create `PhaseTemplate` type: `{ capability: Capability, template: (target, previousResults) → PhaseExecutionRequest }`
- Create `planner/phase-templates.ts` with 4-6 default templates (GraphQL introspection, JWT scan, Swagger probe, S3 bucket enumeration, CORS misconfig, cloud metadata probe)
- **No runtime behavior changes** — interface only, stubbed

**Files touched:** New `planner/phase-templates.ts`, `planner/replan-rules.ts`, `workflow-runner.ts` (extend types), `bridge/mcp-client.ts` (extend types)

**Effort:** 4-6 hours

---

### 🟡 WEEKS 1-2 — Structural

#### Item 3: Cost Field Dead Metadata + Payload Count Bug

**Language:** TypeScript  
**Existing tests:** `tool-registry.ts` covered by planner executor tests  
**Pre-test:** `bun test argus/unit/planner/`  
**Post-test:** Same + new tests for cost filter safety net

**Current state:** `cost` field never used in `selectBest()`. Payload count bug (Bug D) also fixed here.

**Source:** `tool-registry.ts:selectBest` — no `cost` in sort or filter.

**Acceptance criterion:**
- `selectBest()` accepts `costFilter?: "all" | "low_only" | "no_high"` (default `"all"`)
- Filtering is **tier-specific**: a capability is "covered" if ≥1 tool at the filtered cost tier provides it
- **Safety net:** if filter would leave a capability uncovered, warn and include high-cost tools for that capability only; tools with no `cost` default to `"medium"`
- Payload count fixed (Bug D)

**Files touched:** `tool-registry.ts`, `tool-definitions.yaml`, `config/constants.py`

**Effort:** 2 days

---

#### Item 4: Version Fields Dead in YAML + Doctor Hardcoded Checks

**Language:** TypeScript + YAML  
**Existing tests:** `doctor.ts` has no direct test file; `workflows/approval.test.ts` covers gate logic  
**Pre-test:** `bun test argus/unit/workflows/`  
**Post-test:** Same + new tests for version field loading

**Current state:** Only `nuclei.yaml` sets version fields. `doctor.ts` has hardcoded `TOOL_VERSION_CHECKS`.

**Acceptance criterion:** Add `version_cmd`, `min_version`, `version_regex` to `ToolDef`. Refactor `doctor.ts` to read from loaded registry. **30-second timeout per version check.** All 12 doctor-checked tools include version fields in YAML.

**Files touched:** `tool-registry.ts`, `doctor.ts`, 12 tool YAMLs, `tool-definitions.yaml`

**Effort:** 3 days

---

#### Bug B: Streaming M-07 Investigation + Redis Adapter (conditional)

**Language:** Python  
**Existing tests:** None — must create  
**Pre-test:** `pytest argus-workers/test_streaming.py` (new)  
**Post-test:** Same

**Current state:** SSE-only; Redis removed during M-07 consolidation. Comments at `streaming.py:727,777,867` confirm deliberate removal but don't state rationale.

**Acceptance criterion (conditional on investigation):**
1. **Phase 1 (Week 1): Investigate M-07** — `git log --grep="M-07" -- streaming.py`, `git show <commit>`, check issue tracker. Document findings in `docs/STREAMING_REMOVAL_RATIONALE.md`
2. **Phase 2 (Week 3-4, conditional):** If M-07 removal was (a) scope cut with no technical issues → implement `RedisEventBus` with thread pool bridge. If (b) reliability issues → use Redis Streams or persistent queue, not pub/sub. If (c) security → add Redis AUTH/TLS.
3. **Phase 2b (Week 3-4, alternative):** If M-07 reveals fundamental issues with cross-process streaming → defer per Capability Roadmap.

**Fallback:** `ARGUS_REDIS_EVENTS=1` or `REDIS_URL` enables adapter. Falls back to in-process when unavailable. All `emit_*` functions remain synchronous.

**Files touched:** `streaming.py` (~200 lines new code), new `docs/STREAMING_REMOVAL_RATIONALE.md`

**Effort:** 1 day (investigation) + 1-2 days (implementation, conditional)

---

### 🟡 WEEKS 2-3 — DB/TUI Bundle

#### Item 5: N+1 Queries + Dual-Mode Design for 14b

**Language:** TypeScript  
**Existing tests:** `store.test.ts` (integration), `engagement-store.test.ts` (unit)  
**Pre-test:** `bun test argus/integration/store.test.ts` + `bun test argus/unit/engagement-store.test.ts`  
**Post-test:** Same + new tests for dual-mode

**Current state:** `listEngagements()` then N×`getFindings(e.id)`. `GROUP BY` won't work under 14b.

**Acceptance criterion:**
- `workspace.tsx` issues exactly 2 queries regardless of engagement count
- **Dual-mode design:** `getFindingCountsByEngagementIds()` implements both paths:
  - **Single-DB path** (active now): `GROUP BY` query
  - **Per-engagement path** (stubbed for 14b): `Promise.all` over per-engagement DBs, **throws `"Not yet implemented"` with reference to Item 14b**

**Files touched:** `workspace.tsx`, `store.ts`, `engagement/store.ts`

**Effort:** 2 days

---

#### Item 6: Skeleton Loading + `getEngagementDetail()` Transaction

**Language:** TypeScript  
**Existing tests:** `engagement-detail.tsx` test coverage unknown  
**Pre-test:** `bun test argus/`  
**Post-test:** Same

**Current state:** Binary spinner only. 4 separate DB queries on mount.

**Acceptance criterion:** Skeleton blocks matching card layout. `getEngagementDetail()` returns all data in one SQLite transaction. `skeletonChar: string` configurable in theme (default `#`).

**Files touched:** `engagement-detail.tsx`, `store.ts`, `theme.ts`

**Effort:** 2 days

---

#### Item 7: Audit Log Filter Bar

**Language:** TypeScript  
**Existing tests:** N/A (new UI feature)  
**Pre-test:** `bun test argus/`  
**Post-test:** Same

**Acceptance criterion:** Filter bar with All / Phase / Tool / Error. Client-side filtering via `createSignal`. Filter persists during session.

**Files touched:** `engagement-detail.tsx` only

**Effort:** 1 day

---

### 🟡 WEEKS 3-4 — Credential + Replanning

#### Item 8: Playwright BOLA + Generated Script Execution (expanded)

**Language:** TypeScript + Python  
**Existing tests:** None for credential helper — must create  
**Pre-test:** `bun test argus/` + `pytest argus-workers/tools/test_credential_helper.py` (new)  
**Post-test:** Same  
**New test files:** `argus-workers/tools/test_credential_helper.py` (temp file creation, permissions, cleanup)

**Current state:** `playwright-bola.yaml` params mismatch Python script. `ChainExploitGenerator` scripts persisted but never executed. Both need same credential execution pattern.

**Acceptance criterion:**
1. **`resolveToolCredentials()` helper** created: reads roles from `CredentialStore`, writes temp JSON file with `0o600` permissions, deletes in `finally` block. No PII in process lists.
2. **Playwright BOLA** uses `--creds-file` via helper (Bug C fix).
3. **ChainExploitGenerator scripts** read from `attack_paths.chain_exploit_script`, written to temp file via same helper, executed via `subprocess.run()`, captured as proof-of-impact.
4. Helper is shared — BOLA + exploit execution both use same `resolveToolCredentials()`.

**Files touched:** `playwright-bola.yaml`, `executor.ts` (new helper), `tool-registry.ts` (add `credential_roles`), `mcp_server.py`, `tool_runner.py` (add `run_generated_script()`), `attack_graph_db.py`

**Effort:** 2-3 days (was 1d, expanded for shared helper + exploit integration)

---

#### Item 14a: Configurable Base Path

**Language:** TypeScript  
**Existing tests:** `store.test.ts`, `engagement-store.test.ts`  
**Pre-test:** `bun test argus/`  
**Post-test:** Same

**Current state:** 5 hardcoded paths to `~/.argus/`.

**Acceptance criterion:** All 5 paths use `StoragePaths` reading from `ARGUS_DATA_DIR` or `storage.base_path`. Migration command `argus storage migrate --from ~/.argus --to /new/path` copies data and verifies integrity.

**Files touched:** New `storage/paths.ts`, `store.ts`, `credentials.ts`, `doctor.ts`, `tool-config.ts`, `config/loader.ts`, `argus.config.yaml`

**Effort:** 2-3 days

---

### 🟡 WEEKS 4-5 — Replanning + Concurrency

#### Item 15b: Replanning Implementation (activates 15a interface)

**Language:** TypeScript + Python  
**Existing tests:** None for replanning logic — must create  
**Pre-test:** `bun test argus/` + `pytest argus-workers/test_replan.py` (new)  
**Post-test:** Same  
**New test files:** `argus-workers/test_replan.py` (phase insertion, capability detection, contract extension)

**Current state:** `_replan()` stub returns `{"status": "done"}`. Phase templates exist (from 15a) but unused. Stubbed fields on `PhaseRecord` are undefined.

**Acceptance criterion:**
- MCP `agent_init` contract activated: `phaseDefinition` and `capabilityMap` populated
- `_replan()` detects novel capabilities from `context.findings`, looks up matching phase templates from `planner/phase-templates.ts`, returns new phase definitions
- TypeScript `workflow-runner.ts` receives new phase definitions and adds them to `plan.phases`
- No DB schema changes required (columns already exist from Week 1 Item 2)
- Depends on Item 2's Map structure and Item 15a's interface design

**Files touched:** `mcp_server.py`, `workflow-runner.ts`, `bridge/mcp-client.ts`, `planner/planner.ts` (activate templates)

**Effort:** 3-4 days

---

#### Item 9: Global Subprocess Concurrency (corrected)

**Language:** Python  
**Existing tests:** None — must create  
**Pre-test:** `pytest argus-workers/test_concurrency.py` (new)  
**Post-test:** Same  
**New test files:** `argus-workers/test_concurrency.py` (semaphore behavior, high-cost tool list, per-worker limit)

**Current state (corrected):** `MAX_CONCURRENT_REQUESTS=20` defined but never enforced. Independent `ThreadPoolExecutor`s in recon(8), scan(5) — these are **scheduling threads** (light, I/O-bound), not execution subprocesses. They should remain independent.

**Acceptance criterion (corrected from v3.0):**
- **Keep** orchestrator `ThreadPoolExecutor`s (recon=8, scan=5) for tool scheduling — they are scheduling threads, not subprocess limits
- **Add** `SUBPROCESS_SEMAPHORE` at `tool_runner.py` level gating all `subprocess.run()` calls
- **Add** `HIGH_COST_SEMAPHORE` (stricter, ~⅓ of general limit) for sqlmap/dalfox/commix/nuclei/masscan/sn1per
- Per-worker limit = `MAX_CONCURRENT_SUBPROCESSES / EXPECTED_WORKERS` (minimum 2). Warning if < 2.
- TS shows `⌛` if no tool output within 10s

**Files touched:** New `runtime/concurrency.py`, `tool_runner.py`

**Files NOT touched:** `recon.py`, `scan.py`, `web_scanner.py` — their executors stay independent

**Effort:** 2-3 days (including Python test creation)

---

### 🟢 WEEKS 5-7 — Infrastructure

#### Item 10: Docker Networking

**Language:** Config  
**Existing tests:** None — manual  
**Pre-test:** N/A  
**Post-test:** Manual Docker test

**Acceptance criterion:** `extra_hosts: ["host.docker.internal:host-gateway"]` for worker service. Requires Docker 20.10+ on Linux.

**Files touched:** `docker-compose.yml`, `README.md`

**Effort:** 1 day

---

#### Item 11: DNS Pre-Flight Check

**Language:** TypeScript  
**Existing tests:** N/A — new doctor check  
**Pre-test:** `bun test argus/`  
**Post-test:** Same

**Acceptance criterion:** `doctor.ts` checks `dns.google:53` resolution; emits actionable error with remediation.

**Files touched:** `doctor.ts`

**Effort:** 1 day

---

### 🟢 ONGOING — Infrastructure (Parallel, Weeks 5-10)

#### Item 12: Air-Gap Build

**Acceptance criterion:** `ARG AIRGAP=0` at top of Dockerfile. Internet steps wrapped in `if`. For `AIRGAP=1`, tools in `./vendor/`. README documents.

**Files touched:** `Dockerfile`, `README.md`

**Effort:** 2-3 days

---

#### Item 13: Git Host Policy

**Acceptance criterion:** `argus.config.yaml` includes `scope.git_host_policy: "allowlist" | "allow_all"`. Python `GitSSRFConfig.from_config()` reads from YAML. Empty allowlist blocks all. TS validates. Document hot-reload limitation.

**Files touched:** `argus.config.yaml`, `config/constants.py`, `config/loader.ts`

**Effort:** 2 days

---

#### Item 14b: Per-Engagement Subdirectories + Encryption Seam

**Language:** TypeScript  
**Existing tests:** `store.test.ts` (integration), `engagement-store.test.ts` (unit)  
**Pre-test:** `bun test argus/integration/store.test.ts`  
**Post-test:** Same + migration tests

**Current state:** Single SQLite DB at `~/.argus/argus.db`.

**Acceptance criterion:**

**Migration strategy (two-phase with atomic switch):**

```
Phase 1 (Copy — safe, idempotent, retryable):
├── For each engagement:
│   ├── Create ~/.argus/engagements/<id>/ directory
│   ├── Create engagement.db with schema
│   ├── Copy findings via INSERT ... SELECT
│   ├── Copy evidence (file copy)
│   ├── Copy audit log entries
│   └── Write per-engagement marker: .migration_complete
└── Phase 1 marker: ~/.argus/.migration_phase1_complete

Phase 2 (Atomic Switch — single filesystem write):
├── Verify all .migration_complete markers present
├── Write schema version marker: _argus_metadata (schema_version=2)
├── Preserve old DB as ~/.argus/argus.db.backup
└── Phase 2 is atomic: one write
```

**Non-interleaving guarantee:** Migration checks for active scans before starting. If active scans detected, aborts with clear error. `--force` flag available with user confirmation.

**Rollback:** If Phase 1 fails, delete partial engagement directories and retry. If Phase 2 fails, restore old DB from backup and revert schema marker.

**Encryption seam (not interface):** Add `EncryptionProvider` abstract class with single method `wrapConnection(dbPath: string): Promise<Database>`. Include `NullEncryptionProvider` (no-op, returns `DatabaseSync` directly). `EngagementStore` constructor accepts optional `EncryptionProvider`. **No `encrypt()`/`decrypt()` methods** — the seam defers strategy to Item 14c (SQLCipher, filesystem, or record-level).

**Dual-mode:** `getFindingCountsByEngagementIds()` per-engagement path activated (see Item 5).

**Files touched:** `storage/paths.ts`, `store.ts`, new `storage/encryption.ts`, `storage/migration.ts`, `cli.ts` (migration command)

**Effort:** 1-2 weeks (migration + encryption seam + CLI command + testing)

---

#### Item 14c: Encryption at Rest

**Current state:** Everything unencrypted.

**Acceptance criterion:** **Deferred pending security review.** Implements `EncryptionProvider` from 14b. Concrete provider chosen by security review (SQLCipher recommended; filesystem or record-level as alternatives). Key in OS keychain (libsecret/Linux, Keychain/macOS).

**Test tag:** `[security-review]`

**Files touched:** TBD after review

**Effort:** Weeks (pending review + security sign-off)

---

## Out of Scope — Deferred Capabilities

The following were confirmed missing during source audit but are **not addressed by this plan**. They require new feature development (new modules, new cross-boundary contracts, new agent-loop behavior), not refactoring of existing plumbing.

| Capability | Evidence | Effort | Rationale for Deferral |
|-----------|----------|--------|------------------------|
| **Adaptive encoding** | `grep for encoding pipeline/classes: zero results` | 2-3 weeks | Requires new `EncodingPipeline` module + LLM prompt changes + agent loop integration |
| **Blockade detection** | `grep for BlockadeFinding: zero results` | 1-2 weeks | Requires new `BlockadeFinding` type + response analyzer + WAF indicator patterns |
| **Session rotation** | `auth_context.py:19` — single auth, no expiry | 1-2 weeks | Requires `AuthContext` → `SessionPool` refactor + credential expiry + Playwright tool updates |

**Next step:** Create "Argus Capability Roadmap v1" to scope and schedule these. Target: after this plan completes (Week 10).

---

## Estimate Confidence

All line-item estimates are **90% likely** — there is a 90% probability the work will take ≤ the stated time. They assume:

- **1 engineer** working uninterrupted on the item
- **Familiarity with the codebase** (the person has read all referenced source files)
- **Code review** included (30-60 min per item)
- **Test writing** included (matching the language-specific QA gate)
- **No regressions** that require revisiting previous items

**Historical variance from v3.0:** Python test creation added 1-2 days per Python item. The schedule grew from 6-8 weeks to 8-10 weeks as a result.

**If 2 engineers available:** parallelize Week 1 items (Bug C, Bug D, Item 1, Item 2, Item 15a) across 2 engineers, reducing total calendar time to 5-7 weeks (but same person-hours).

---

## Suggested Execution Order

| Week | Items | Effort (1 eng.) | Dependencies Met |
|------|-------|------------------|------------------|
| **Week 1** | Bug C (1h), Bug D (10m), Bug B Phase 1 (1d), Item 1 (2d), Item 2 (2-3d), Item 15a (1d) | ~7 days | Item 15a precedes Item 2; Bug B investigation starts |
| **Week 2** | Item 3 (2d), Item 4 (3d), Item 7 (1d) | ~6 days | Item 2 Map structure stable for Item 3/4/7 |
| **Week 3** | Item 5 (2d), Item 6 (2d), Item 14a (2-3d), Bug B Phase 2 (2d) | ~9 days | Bug B Phase 2 conditional on Phase 1 findings |
| **Week 4** | Item 8 (2-3d), Item 15b (3-4d) | ~7 days | Item 15b depends on Item 2 + Item 15a |
| **Week 5** | Item 9 (2-3d), Item 10 (1d), Item 11 (1d) | ~5 days | Concurrency needs real-target testing |
| **Week 6** | Item 12 (2-3d), Item 13 (2d) | ~4-5 days | Infrastructure work; can parallelize |
| **Week 7-10** | Item 14b (1-2w) | ~1-2 weeks | Depends on Item 14a (base path); includes encryption seam + migration |

**Total: 8-10 weeks (1 engineer).**

**If Bug B Phase 1 reveals fundamental issues with cross-process streaming:** Bug B moves to "Deferred" and Week 3 shrinks to ~7 days.

---

## Definition of Done (Per Item)

**Language-specific QA gates:**

| Language | Pre-Step | Post-Step | New Tests Required |
|----------|----------|-----------|--------------------|
| **TypeScript** | `bun test argus/` — verify all green | Same command — verify all green + new tests pass | Add/modify tests for changed files |
| **Python** | `pytest <changed_files>` — if file exists, verify green | Same command — must pass | **≥1 unit test per changed file** covering happy path, error path, security path |
| **Config/YAML** | Manual verification | Manual verification | Integration test or manual checklist |

**All items additionally require:**

1. **Acceptance criterion met** (from item table above)
2. **Test tag satisfied** (`[CI/unit]`, `[CI/integration]`, `[manual]`, or `[security-review]`)
3. **Docs updated** if user-facing (CLI flags, TUI behavior, config changes)
4. **Source verification** — reviewer confirms claim matches code at file:line
5. **No new regressions** in existing tests (for TypeScript; Python tests are new)

---

## References

All claims verified against source code at these locations:

| File | Lines | Claim Verified |
|------|-------|---------------|
| `agent/react_agent.py` | 58-73, 848-1097 | Agent loop implementation |
| `agent_loop.py` | 1-11 | Re-exports agent loop |
| `intelligence_engine.py` | 179, 467, 647, 1114, 1210 | Confidence scoring, enrichment, coverage gaps |
| `attack_graph.py` | 31-104, 565-593 | Chain templates, risk scoring |
| `llm_client.py` | 91-104, 132-138, 260-321, 572-574 | Providers, breaker, rate limit, cost |
| `llm_payload_generator.py` | 34, 109, 216, 270 | Payload count bug |
| `tools/scripts/playwright_bola.py` | 16-67 | BOLA implementation |
| `mcp_server.py` | 761-766, 790-791 | Replan stub, error feedback |
| `circuit_breaker.py` | 26-119 | Circuit breaker implementation |
| `streaming.py` | 194-341, 727, 867 | SSE-only, no Redis |
| `cache.py` | 98-312 | Cache implementation |
| `tool_definitions.py` | 88-167 | 65 tools with metadata |
| `_generated_tools.py` | 6 | Tool count confirmation |
| `config/constants.py` | 34, 93-130 | Payload limit, GitSSRF config |
| `chain_exploit_generator.py` | 1-11, 81-97, 100-469 | LLM exploit script generation |
| `auth_context.py` | 19 | Single auth context |
| `react_agent.py` | 248-254 | Auth context usage |
| `Argus-Tui/packages/opencode/test/argus/unit/workflow-runner.test.ts` | 73-540 | Existing TypeScript test coverage |
| `Argus-Tui/packages/opencode/test/argus/integration/store.test.ts` | 80-184 | Existing store test coverage |

---

*Plan version: 4.0 — Corrected after 8-question line-level stress test (2026-06-24)*
*Schedule: 8-10 weeks (1 engineer)*
*16 items + 4 bugs; 3 capabilities deferred to separate roadmap*
