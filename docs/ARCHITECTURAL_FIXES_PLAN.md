# Argus Architectural Fixes Plan — Consolidated

**Status:** Final, after codebase validation and design interview
**Date:** 2026-06-23
**Author:** Architecture review board

This document consolidates all 14 items from the architectural fixes plan, validated
against the actual codebase and refined through design decisions made during the
review interview. Every item has been traced back to its source files, assessed for
accuracy, and scoped to a specific week.

---

## Summary of Design Decisions

| Decision | Outcome | Affected Items |
|----------|---------|----------------|
| **Dual YAML sources** | Keep separate. TS `tool-definitions.yaml` is the planner's selection index; Python `tools/definitions/*.yaml` are execution manifests. Synchronize shared fields (`cost`, `signal_quality`, `priority`) by copying values from Python into TS YAML. Does not merge. | 3, 4, 8 |
| **Scan depth / `cost` filter** | **Branch C (plumbing only).** Add `costFilter?: CostFilter` param to `selectBest()`, default `"all"`. Wire `quick_scan.yaml` to pass `"no_high"` internally. No CLI/TUI flags yet. Defer UX design. | 3, 9 |
| **Playwright BOLA credentials** | **Branch B + `credential_roles` field.** Add optional `credential_roles: string[]` to YAML/ToolDef. **Prerequisite: fix YAML/Python arg mismatch** (YAML declares `--attacker-username` but script expects `--creds-file`). Wire `resolveToolCredentials()` in executor. Wire `requires: { credentials: true }` into `passesGates()`. | 8 |
| **Rate limiting primitive** | `threading.BoundedSemaphore` at `tool_runner.run()/run_streaming()` chokepoint. NOT `asyncio.Semaphore` — the main execution path is synchronous. Add separate `HIGH_COST_SEMAPHORE` for heavy tools. TS side `MAX_PARALLEL_TOOLS=4` stays unchanged. | 9 |
| **Phase indexing** | Refactor `addPhase()`/`completePhase()` to accept `phaseId` instead of positional index. Convert `phaseRecords[]` to `Map<string, PhaseRecord>` + `phaseOrder[]` for execution ordering. | 2 |
| **Skeleton loading** | **Option (b) — structural skeleton.** Placeholder block characters (`▓`/`░`) in `theme.textMuted` matching the page layout. Not simple spinner, not tab-by-tab lazy. | 6 |
| **`allowed_git_hosts` policy** | **Option (b) — add `git_host_policy` field.** Python enforces, TS surfaces. `GitSSRFConfig.from_config()` reads YAML. Add `ScopeConfigSchema` to TS Zod schema. | 13 |
| **Data residency (14a) timing** | **Bundle with Week 2.** Start subproject (a) alongside items 5, 6, 7 since they all touch `store.ts`. Create `storage/paths.ts` utility. | 14(a), 5, 6, 7 |

---

## Week 1 — Priority 1: Self-Contained, No Design Dependencies

### Item 1: Python Circuit Breaker reads hardcoded values

**Status:** ✅ **Fixed** — circuit breaker reads from `argus.config.yaml` via `constants.py`
**Files:** `argus-workers/tools/tool_runner.py`, `argus-workers/config/constants.py`

**Completed 2026-06-26:**
- `tool_runner.py:20` imports `CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_COOLDOWN` from `config.constants`
- `tool_runner.py:97-98` uses them as `__init__` parameter defaults
- `tool_runner.py:131-132` passes them to `ToolCircuitBreakerManager()`
- Data flow: `argus.config.yaml` → `ConfigManager` → `CircuitBreakerConfig.from_config()` → `CONFIG.circuit_breaker` → module-level constants → `ToolRunner.__init__()` params → `ToolCircuitBreakerManager()`

The TS-side `ToolConfig` in `tool-config.ts` already correctly reads circuit breaker config from `argus.config.yaml` (lines 71-75). Both sides now respect the YAML config.

**Effort:** ~5 minutes, 3 lines

---

---

### Item 2: scan-store.ts positional phase indexing

**Status:** ✅ **Fixed** — phase indexing uses `Map<string, PhaseRecord>` with ID-based lookups
**Files:** `Argus-Tui/packages/opencode/src/argus/tui/scan-store.ts`,
`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`,
`Argus-Tui/packages/opencode/src/argus/commands/resume.ts`

**Completed 2026-06-26:**

**`workflow-runner.ts`:**
- Converted `phaseRecords: PhaseRecord[]` array → `Map<string, PhaseRecord>` keyed by phase ID
- All indexed access replaced with O(1) Map lookups (`phaseRecords.get(phase.phaseId)!`)
- Replan phase push uses `map.set()` instead of `push()`
- `savePhases()` calls convert Map to array via `Array.from(phaseRecords.values())`

**`resume.ts`:** Same refactoring applied to `allPhaseRecords` (identical pattern)

**`scan-store.ts`:**
- `addPhase()` now checks for existing phase ID via `findIndex()` before adding, preventing replan phase duplication in scan state
- `completePhase()` already used `phaseId`-based lookup (no change needed)
- `processEventInner()` already called the ID-based versions (no change needed)

**Effort:** ~45 minutes

---

### Item 3: `cost` field is dead metadata

**Status:** ✅ **Fixed** — `selectBest()` accepts `costFilter` parameter; all tools have `cost` populated
**Files:** `Argus-Tui/packages/opencode/src/argus/workflows/tool-registry.ts`,
`Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml`,
`Argus-Tui/packages/opencode/src/argus/planner/planner.ts`

**Completed 2026-06-26:**

**`tool-registry.ts`:**
- Added `export type CostFilter = "all" | "low_only" | "no_high"`
- Added optional `costFilter?: CostFilter` parameter to `selectBest()`
- Added cost filter loop with safety net: removes tools that fail the filter, but keeps them for capabilities that would otherwise have zero tools
- Added `_passesCostFilter()` private helper
- Default cost for undefined is `"medium"` (matching existing tiebreaker behavior)

**`planner.ts`:**
- When workflow name is `"quick_scan"`, passes `costFilter: "no_high"` to `selectBest()`, excluding high-cost tools (sqlmap, masscan, commix, semgrep, etc.) from the quick scan path
- Other workflows pass `undefined` (no behavior change)

**`tool-definitions.yaml`:**
- All external tools already had `cost:` populated (nuclei, nmap, nikto, etc.)
- Fixed `ffuf` (cost: medium) and `sqlmap` (cost: high) — their `cost` was incorrectly nested inside the `scoring:` block instead of at the top level, making it invisible to `ToolDef.cost`
- Cost values match the table to the right (already verified against Python YAMLs)

**Effort:** ~1-2 hours (multi-file but well scoped)

---

### Item 4: `version_cmd` / `min_version` / `version_regex` missing from TS YAML

**Status:** ✅ **Fixed** — version fields populated for 46 external tools; `doctor.ts` reads from registry via `loadToolVersionChecks()`
**Files:** `Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml`,
`Argus-Tui/packages/opencode/src/argus/workflows/tool-registry.ts`,
`Argus-Tui/packages/opencode/src/argus/commands/doctor.ts`,
`Argus-Tui/packages/opencode/test/argus/unit/commands/doctor.test.ts`

**Completed 2026-06-26 (earlier session):**

All three parts were implemented in a previous session:

1. **`ToolDef` interface** in `tool-registry.ts` — already has `version_cmd?: string`, `min_version?: string`, `version_regex?: string`

2. **`tool-definitions.yaml`** — all 46 external tools have `version_cmd` and `version_regex` populated (matching the table below). Most tools have `min_version: "1.0.0"` as a sensible default. Nuclei has `min_version: "3.0.0"`.

| Tool | `version_cmd` | `min_version` | `version_regex` |
|------|---------------|---------------|-----------------|
| nuclei | `nuclei --version` | `3.0.0` | `\d+\.\d+\.\d+` |
| nmap | `nmap --version` | `1.0.0` | `\d+\.\d+` |
| nikto | `nikto -Version` | `1.0.0` | `\d+\.\d+\.\d+` |
| whatweb | `whatweb --version` | `1.0.0` | `\d+\.\d+\.\d+` |
| ffuf | `ffuf -V` | `1.0.0` | `\d+\.\d+` |
| httpx | `httpx -version` | `1.0.0` | `\d+\.\d+\.\d+` |
| subfinder | `subfinder -version` | `1.0.0` | `\d+\.\d+\.\d+` |
| dalfox | `dalfox version` | `1.0.0` | `\d+\.\d+\.\d+` |
| gitleaks | `gitleaks version` | `1.0.0` | `\d+\.\d+\.\d+` |
| trivy | `trivy --version` | `1.0.0` | `\d+\.\d+\.\d+` |
| semgrep | `semgrep --version` | `1.0.0` | `\d+\.\d+\.\d+` |
| katana | `katana -version` | `1.0.0` | `\d+\.\d+\.\d+` |

3. **`doctor.ts`** — hardcoded `TOOL_VERSION_CHECKS` array already removed. `loadToolVersionChecks()` reads from the tool registry via YAML, and `toolchainCheck()` builds `versionCheckMap` from it. `parseSemver()` and `compareVersions()` are exported helpers. Unit tests exist in `doctor.test.ts` covering all three.

**Effort:** ~1-2 hours (completed in prior session)

---

## Week 2 — Priority 2 + Data Residency Subproject (a) Bundled

### Item 5: N+1 queries in workspace.tsx

**Status:** ✅ **Fixed in this session** — also fixed same pattern in dashboard.tsx, engagements.tsx, evidence.ts; rewrote `getEvidenceByEngagement()` with 3 bulk queries; extracted `_inClause` helper with `SQL | AnyColumn` typing; added unit tests for `getFindingCountsByEngagementIds()` and `getEvidenceByEngagement()`
**Files:** `Argus-Tui/packages/opencode/src/argus/tui/routes/workspace.tsx`,
`Argus-Tui/packages/opencode/src/argus/engagement/store.ts`

**Problem:**
`workspace.tsx` lines 26-33 calls `store.listEngagements()` (1 query) then loops
`store.getFindings(e.id)` for each engagement (N queries). This is N+1.

**Fix:**
Add `getFindingCountsByEngagementIds(ids: string[]): Map<string, number>` to
`EngagementStore` that does a single grouped query:

```sql
SELECT engagement_id, COUNT(*) FROM findings
WHERE engagement_id IN (?, ?, ...)
GROUP BY engagement_id
```

Call it once in `workspace.tsx` after `listEngagements()`, then join results in
memory. The store already has `getEvidenceCountsByEngagement()` (line 534)
demonstrating this pattern.

**Effort:** ~30 minutes

---

### Item 6: engagement-detail.tsx 4 separate DB queries on mount

**Status:** ✅ **Fixed in this session** — added `getEngagementDetail()` bundled method to `EngagementStore`; implemented structural skeleton loading with block characters (`▓`/`░`) matching page layout
**Files:** `Argus-Tui/packages/opencode/src/argus/tui/routes/engagement-detail.tsx`,
`Argus-Tui/packages/opencode/src/argus/engagement/store.ts`

**Problem:**
`engagement-detail.tsx` `onMount` (lines 34-59) makes 4 sequential store calls:
`getEngagement()`, `getFindings()`, `getEvidenceByEngagement()`, `getAuditLog()`.
Each is a separate SQL SELECT. No skeleton state — just a binary spinner.

**Fix:**
1. Add `getEngagementDetail(id): { engagement, findings, evidence, auditLog }`
   to `EngagementStore` that runs all 4 SELECTs inside a single method call.
2. Implement **structural skeleton loading (Option b):** while data loads, show
   placeholder block characters (`▓`/`░`) in `theme.textMuted` matching the page
   layout — header bars, tab row, and 5 list item placeholders. Keep the
   `⠋ Loading...` spinner as the first skeleton line.

```tsx
// Skeleton components (~20 lines total)
function SkeletonLoading() {
  const { theme } = useTheme()
  return (
    <box flexDirection="column" padding={1}>
      <text fg={theme.primary}>⠋ Loading engagement...</text>
      <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</text>
      <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</text>
      <box flexDirection="row">
        <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓ </text>
        <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓ </text>
        <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓ </text>
        <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓</text>
      </box>
      <For each={Array.from({ length: 5 })}>{() => (
        <box flexDirection="column" marginBottom={1}>
          <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</text>
          <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</text>
        </box>
      )}</For>
    </box>
  )
}
```

**Effort:** ~1 hour (30 min store method + 30 min skeleton)

---

### Item 7: engagement-detail.tsx audit log not filtered

**Status:** ✅ **Fixed in this session** — added `eventFilter` signal (`"all" | "phase" | "tool" | "error"`), `eventCategory()` mapping by event type prefix, and clickable filter bar above timeline entries
**Files:** `Argus-Tui/packages/opencode/src/argus/tui/routes/engagement-detail.tsx`

**Problem:**
Timeline tab (lines 158-173) renders all audit log entries unfiltered. Each entry
has `eventType` (line 29: `eventType: string`) but no filter UI exists.

**Fix:**
1. Add a `createSignal<"all" | "phase" | "tool" | "error">("all")` for the filter.
2. Render a filter bar above the timeline with clickable filter options.
3. Filter the `timeline()` array client-side before rendering.
4. Audit logs per engagement are small (typically <200 entries) — no performance concern.

**Effort:** ~30 minutes

---

### Subproject 14(a): Configurable storage base path

**Status:** ✅ **Fixed in this session** — created `StoragePaths` utility with `ARGUS_DATA_DIR` env var / `storage.base_path` config / `~/.argus` fallback; replaced 11 hardcoded paths across 8 files; added unit tests pass
**Files:** `Argus-Tui/packages/opencode/src/argus/storage/paths.ts` (new),
`Argus-Tui/packages/opencode/src/argus/engagement/store.ts`,
`Argus-Tui/packages/opencode/src/argus/engagement/credentials.ts`,
`Argus-Tui/packages/opencode/src/argus/commands/doctor.ts`,
`Argus-Tui/packages/opencode/src/argus/config/tool-config.ts`,
`Argus-Tui/packages/opencode/src/argus/config/loader.ts`,
`argus.config.yaml`

**Problem:**
All storage paths are hardcoded to `~/.argus/`:
- `store.ts:68` → `join(homedir(), ".argus", "argus.db")`
- `credentials.ts:15` → `join(homedir(), ".argus", "credentials.json")`
- `doctor.ts:264` → `~/.argus/argus.db`
- `tool-config.ts:40` → `join(homedir(), ".argus", "config.yaml")`
- `config/loader.ts` → `join(homedir(), ".argus", "config.yaml")`

No env var override. No config field. No shared path utility.

**Fix (one afternoon):**
1. Create `storage/paths.ts`:
```typescript
const StoragePaths = {
  get basePath(): string { /* ARGUS_DATA_DIR > storage.base_path in config > ~/.argus */ },
  get dbPath() { return join(this.basePath, "argus.db") },
  get credentialsPath() { return join(this.basePath, "credentials.json") },
  get configPath() { return join(this.basePath, "config.yaml") },
  get evidenceDir() { return join(this.basePath, "evidence") },
  get artifactsDir() { return join(this.basePath, "artifacts") },
  engagementDir(id: string) { return join(this.basePath, "engagements", id) },  // for 14(b)
  engagementDbPath(id: string) { return join(this.engagementDir(id), "engagement.db") },
}
```

2. Update all 5 hardcoded path sites to use `StoragePaths`.
3. Add `storage.base_path` to `argus.config.yaml`.

**Effort:** ~1 afternoon (~100 lines total)

---

## Week 3 — Priority 2/3 Mixed

### Item 8: Playwright BOLA tool params not reachable

**Status:** ✅ **Fixed** — YAML/Python mismatch fixed, credentials gate wired, credential_roles metadata added
**Files:** `argus-workers/tools/definitions/playwright-bola.yaml`,
`argus-workers/tools/scripts/playwright_bola.py`,
`Argus-Tui/packages/opencode/src/argus/workflows/tool-registry.ts`,
`Argus-Tui/packages/opencode/src/argus/planner/executor.ts`,
`argus-workers/mcp_server.py`

**Completed 2026-06-26:**

**Prerequisite bug — already fixed (prior session):**
The YAML (`playwright-bola.yaml`) already uses `--creds-file` and `playwright_bola.py` also accepts `--creds-file`. They are aligned.

**Credential role support (this session):**
1. ✅ `credential_roles?: string[]` — already in `ToolDef` interface (prior session)
2. ✅ **Wired `requires: { credentials: true }` into `passesGates()`** — `tool-registry.ts` now checks if `requires.credentials === true` and blocks the tool when `context.hasAnyCredentials === false`. Added `credentials?: boolean` to `RequiresGate` interface. Added `availableCredentialRoles` and `hasAnyCredentials` to `GateContext`.
3. ✅ **`buildCredsFile()`** — already in `executor.ts` (prior session). Reads `toolDef.credential_roles` (defaults to `["attacker", "victim"]`), looks up roles from `CredentialStore`, writes temp file with mode 0o600.
4. ✅ **`credential_roles` added to Python `ToolDefinition`** in `mcp_server.py` — added parameter to `__init__()` and serialized in `to_dict()`.
5. ✅ **`credential_roles` added to YAML definitions:**
   - `playwright-bola.yaml` → `["attacker", "victim"]`
   - `playwright-xss.yaml` → `["default"]`
   - `playwright-privesc.yaml` → `["default"]`

**Effort:** ~2 hours (split across 2 sessions)

---

### Item 11: No proactive DNS validation

**Status:** ✅ **Fixed** — DNS pre-flight check in mcp_server.py startup + doctor.ts dnsCheck()
**Files:** `argus-workers/mcp_server.py`, `Argus-Tui/packages/opencode/src/argus/commands/doctor.ts`

**Completed 2026-06-26:**

1. ✅ **`mcp_server.py`** — Added `import socket` and DNS pre-flight check in `MCPServer.__init__()`:
   ```python
   try:
       socket.getaddrinfo("dns.google", 53)
   except socket.gaierror:
       logger.warning(
           "DNS resolution failed — DNS-reliant tools (subfinder, amass, dnsx) may not work. "
           "Check container DNS config or set --dns-servers 8.8.8.8"
       )
   ```
2. ✅ **`doctor.ts`** — Already has `dnsCheck()` function (resolves `dns.google`) wired into `doctorCommand()`. Returns WARN on failure.

Both the Python (MCP server startup) and TS (doctor command) sides now have proactive DNS validation.

**Effort:** ~2 minutes (mcp_server.py: 1 import + 8 lines)

---

## Week 4 — Priority 3 (Requires Testing Against Real Targets)

### Item 9: No global rate limit / concurrency cap

**Status:** ✅ **Fixed** — `runtime/concurrency.py` with semaphores; `tool_runner.py` acquires in both `run()` and `run_streaming()`
**Files:** `argus-workers/runtime/concurrency.py`,
`argus-workers/tools/tool_runner.py`,
`argus-workers/tests/test_concurrency.py`

**Completed prior to 2026-06-26:**

1. ✅ **`runtime/concurrency.py`** — Created with:
   - `SUBPROCESS_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)` (default 20)
   - `HIGH_COST_TOOLS = {"sqlmap", "dalfox", "commix", "nuclei", "masscan", "sn1per"}`
   - `HIGH_COST_SEMAPHORE = threading.BoundedSemaphore(max(1, MAX_CONCURRENT_REQUESTS // 3))`

2. ✅ **`tool_runner.run()`** — Acquires the appropriate semaphore with `with _sem:` before `subprocess.run()`:
   ```python
   _sem = HIGH_COST_SEMAPHORE if tool in HIGH_COST_TOOLS else SUBPROCESS_SEMAPHORE
   with _sem:
       result = subprocess.run(...)
   ```

3. ✅ **`tool_runner.run_streaming()`** — Acquires with `_sem.acquire()` before `subprocess.Popen()`, releases with `_sem.release()` in `finally` block.

4. ✅ **`tests/test_concurrency.py`** — 7 tests validating:
   - Both semaphores are `BoundedSemaphore` instances
   - Initial counts match `MAX_CONCURRENT_REQUESTS` and `MAX_CONCURRENT_REQUESTS // 3`
   - `BoundedSemaphore` rejects releases beyond initial count
   - `HIGH_COST_TOOLS` contains expected tool names and is case-sensitive

5. ✅ **TS side** — `MAX_PARALLEL_TOOLS = 4` left unchanged (phases run sequentially)

**Note:** A Redis-based token bucket would be needed for multi-host distributed
deployment. Documented as future enhancement in code comments.

**Effort:** ~20 lines (completed in prior session)

---

### Item 10: Docker networking — container can't reach localhost targets

**Status:** ✅ **Fixed** — `extra_hosts` added to worker; override file created; README documented
**Files:** `docker-compose.yml`, `docker-compose.override.yml`, `README.md`

**Completed 2026-06-26:**

1. ✅ **`docker-compose.yml`** — Already had `extra_hosts: ["host.docker.internal:host-gateway"]` on the worker service (completed in prior session). Docker 20.10+ on Linux resolves this to the host gateway.

2. ✅ **`docker-compose.override.yml`** — Created with host-network profile:
   ```yaml
   services:
     worker:
       profiles: ["host-network"]
       network_mode: host
   ```

3. ✅ **`README.md`** — Added "Docker Networking" section documenting:
   - Why `host.docker.internal` is needed (bridge network, localhost isolation)
   - How to use `host.docker.internal` as hostname for local targets
   - How to use the compose override for host-network mode

**Effort:** ~15 minutes

---

## Ongoing (Parallel with Other Work)

### Item 12: Air-gap / offline mode in Dockerfile

**Status:** ✅ **Fixed** — all internet fetches wrapped in AIRGAP guard; vendor/ support; README documented
**Files:** `argus-workers/Dockerfile`, `README.md`

**Completed 2026-06-26:**

All internet fetch steps in the Dockerfile are now wrapped in `if [ "$AIRGAP" = "0" ]; then ... fi`:

1. ✅ **`ARG AIRGAP=0`** — Already existed at the top of the file
2. ✅ **apt-get install** — System packages (nmap, nikto, git, curl, ca-certificates)
3. ✅ **Go tarball** — Download, checksum verification, tar extraction, and cleanup
4. ✅ **Go tool installs** — All 10 `go install` commands (nuclei, httpx, subfinder, etc.)
5. ✅ **pip install -r requirements.txt** — Python dependencies
6. ✅ **sqlmap pip install** — sqlmap==1.8
7. ✅ **`vendor/` support** — Documentation added; `COPY . .` naturally includes `vendor/` if present in the build context
8. ✅ **README.md** — Added "Air-Gap / Offline Build" section documenting:
   - Standard vs air-gap build procedures
   - How to pre-populate `vendor/` directory
   - Build command examples

**Air-gap build:**
```bash
cp -r /path/to/pre-fetched/binaries argus-workers/vendor/
docker build --build-arg AIRGAP=1 -t argus-airgap argus-workers/
```

**Effort:** ~30 minutes

---

### Item 13: `allowed_git_hosts: []` allow-all semantics

**Status:** ✅ **Fixed** — dual enforcement aligned between TS and Python
**Files:** `argus.config.yaml`, `argus-workers/config/constants.py`,
`Argus-Tui/packages/opencode/src/argus/shared/target-validator.ts`,
`Argus-Tui/packages/opencode/src/argus/config/loader.ts`

**Completed 2026-06-26:**

1. ✅ **`argus.config.yaml`** — Already had `security.scope.git_host_policy: allowlist` and `security.scope.allowed_git_hosts: []`

2. ✅ **`constants.py`** — `GitSSRFConfig.from_config()` already reads `security.git_host_policy` and `security.allowed_git_hosts` from the YAML. When `policy == "allow_all"`, sets `host_allowlist=()` (empty tuple = all allowed). When `policy == "allowlist"`, merges the curated default list with configured extras.

3. ✅ **`config/loader.ts`** — Already had `ScopeConfigSchema` with both `git_host_policy` and `allowed_git_hosts` fields, validated with Zod.

4. ✅ **`target-validator.ts`** (this session):
   - Updated `SecurityConfig` interface with `git_host_policy?: GitHostPolicy` field
   - Updated `load()` to read `git_host_policy` from both scope-level and top-level YAML paths (scope takes precedence)
   - Updated `isGitHostAllowed()` class method to delegate to the module-level `isGitHostAllowed(host, config)` function, respecting the new policy model
   - Added dual-enforcement JSDoc comments noting Python `constants.py` sync requirement

**Effort:** ~20 minutes (most work done in prior sessions)

---

### Subproject 14(b): Per-engagement storage isolation

**Status:** ✅ **Fixed** — dual-DB architecture with hybrid lazy migration
**Files:** `Argus-Tui/packages/opencode/src/argus/engagement/store.ts`,
`Argus-Tui/packages/opencode/src/argus/storage/paths.ts`,
`Argus-Tui/packages/opencode/src/argus/engagement/schema.sql.ts`

**Completed prior to 2026-06-26:**

The per-engagement storage architecture is fully implemented:

1. ✅ **Root DB** (`argus.db`) — only contains the `engagements` table (metadata + index)
2. ✅ **Per-engagement DBs** — each at `StoragePaths.engagementDbPath(id)`:
   ```
   ~/.argus/
   ├── argus.db              ← engagement index only
   └── engagements/
       ├── ENG-abc123/
       │   ├── engagement.db  ← findings, phases, audit_log, evidence, etc.
       └── ENG-def456/
           └── engagement.db
   ```
3. ✅ **Hybrid lazy migration** — legacy engagements (storage_version=1) still readable from root DB; first write to a legacy engagement auto-creates the per-engagement DB and migrates all data
4. ✅ **Handle caching** — per-engagement DB handles cached with 5-minute idle timeout, cleaned up every 2 minutes
5. ✅ **Schema** — `STORAGE_VERSION_LEGACY=1`, `STORAGE_VERSION_PER_ENGAGEMENT=2`, `STORAGE_VERSION_ENCRYPTED=3`
6. ✅ **Evidence storage** — `evidence.ts` and `verify.ts` use `StoragePaths.engagementsDir`

**Effort:** Implemented in prior session(s)

---

### Subproject 14(c): Encryption at rest

**Status:** Deferred — requires security review
**Files:** TBD

**Problem:**
Everything under `~/.argus/` is unencrypted, single-path, with no confidentiality
protection.

**Fix:**
Three approaches to evaluate:
1. **OS keychain** (libsecret on Linux, Keychain on macOS) for storing encryption key
2. **SQLCipher** for transparent SQLite encryption
3. **File-level encryption** (AES-256-GCM per evidence file)

**Requires:**
- Security review of key derivation and storage
- Decision on key rotation policy
- Migration path for existing unencrypted databases

**Effort:** Weeks + security review. Do not start until 14(b) is stable.

---

## Suggested Execution Order

```
Week 1 ──────────────────────────────────────
  Item 1  (Circuit breaker)     ─ 5 min         ✅ Fixed
  Item 2  (Phase indexing)      ─ 45 min        ✅ Fixed
  Item 3  (Cost metadata)       ─ 1-2 hrs       ✅ Fixed
  Item 4  (Version fields)      ─ 1-2 hrs       ✅ Fixed
  ─── Total: ~1 day ───

Week 2 ──────────────────────────────────────
  Item 5  (N+1 queries)         ─ 30 min     ✅ Fixed
  Item 6  (4 DB queries)        ─ 1 hr       ✅ Fixed
  Item 7  (Audit log filter)    ─ 30 min     ✅ Fixed
  14(a)   (Configurable paths)  ─ 1 afternoon ✅ Fixed
  ─── Total: ~1.5 days ───

Week 3 ──────────────────────────────────────
  Item 8  (Playwright creds)    ─ 2 hrs          ✅ Fixed
  Item 11 (DNS validation)      ─ 30 min         ✅ Fixed
  ─── Total: ~0.5 day ───

Week 4 ──────────────────────────────────────
  Item 9  (Rate limiting)       ─ 20 min code + testing  ✅ Fixed
  Item 10 (Docker networking)   ─ 45 min         ✅ Fixed
  ─── Total: ~0.5 day ───

Ongoing ─────────────────────────────────────
  Item 12 (Air-gap)             ─ 1.5 hrs       ✅ Fixed
  Item 13 (Git host policy)     ─ 1 hr          ✅ Fixed
  14(b)   (Engagement isolation) ─ few days     ✅ Fixed
  14(c)   (Encryption)          ─ weeks + review
```

---

## File Change Summary

| File | Items | Type |
|------|-------|------|
| `argus-workers/tools/tool_runner.py` | 1, 9 | Modify |
| `argus-workers/config/constants.py` | 1, 13 | Modify |
| `argus-workers/tools/circuit_breaker.py` | 1 | Already correct — no change |
| `argus-workers/runtime/concurrency.py` | 9 | **New** |
| `argus-workers/mcp_server.py` | 8, 11 | Modify (3 lines + 10 lines) |
| `argus-workers/tools/definitions/playwright-bola.yaml` | 8 | Modify (fix param mismatch) |
| `argus-workers/tools/scripts/playwright_bola.py` | 8 | Possibly modify for creds-file enhancement |
| `argus-workers/Dockerfile` | 12 | Modify |
| `docker-compose.yml` | 10 | Modify (+ override file) |
| `Argus-Tui/.../tui/scan-store.ts` | 2 | Modify |
| `Argus-Tui/.../tui/routes/engagement-detail.tsx` | 6, 7 | Modify |
| `Argus-Tui/.../tui/routes/workspace.tsx` | 5 | Modify |
| `Argus-Tui/.../engagement/store.ts` | 5, 6, 14(a) | Modify |
| `Argus-Tui/.../engagement/credentials.ts` | 8, 14(a) | Modify |
| `Argus-Tui/.../workflows/tool-registry.ts` | 3, 4, 8 | Modify |
| `Argus-Tui/.../workflows/tool-definitions.yaml` | 3, 4 | Modify |
| `Argus-Tui/.../planner/executor.ts` | 8 | Modify |
| `Argus-Tui/.../planner/planner.ts` | 3 | Modify |
| `Argus-Tui/.../commands/doctor.ts` | 4, 11, 14(a) | Modify |
| `Argus-Tui/.../shared/target-validator.ts` | 13 | Modify |
| `Argus-Tui/.../config/loader.ts` | 13, 14(a) | Modify |
| `Argus-Tui/.../config/tool-config.ts` | 14(a) | Modify |
| `Argus-Tui/.../storage/paths.ts` | 14(a) | **New** |
| `argus.config.yaml` | 13, 14(a) | Modify |
