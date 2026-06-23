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

**Status:** ✅ Valid — confirmed in codebase
**Files:** `argus-workers/tools/tool_runner.py`, `argus-workers/config/constants.py`

**Problem:**
`ToolRunner.__init__()` bakes defaults `failure_threshold=3, cooldown_seconds=300`
at lines 92-93 and creates `ToolCircuitBreakerManager()` with no arguments
at line 126. The `argus.config.yaml` values (`tools.circuit_breaker.max_failures: 5`,
`tools.circuit_breaker.cooldown_ms: 300000`) never reach it.

`config/constants.py` already has `CIRCUIT_BREAKER_THRESHOLD` and
`CIRCUIT_BREAKER_COOLDOWN` at lines 274-275, computed from `CONFIG.circuit_breaker`.

**Fix:**
1. Import `CIRCUIT_BREAKER_THRESHOLD`, `CIRCUIT_BREAKER_COOLDOWN` from
   `config.constants` into `tool_runner.py`
2. Pass them as defaults to the `__init__` parameters
3. Pass them into `ToolCircuitBreakerManager()` at line 126

```python
from config.constants import CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_COOLDOWN

# In __init__:
self._circuit_breaker_mgr = ToolCircuitBreakerManager(
    failure_threshold=self._failure_threshold,
    cooldown_seconds=self._cooldown_seconds,
)
```

**Effort:** ~5 minutes, 3 lines
**Note:** The TS-side `ToolConfig` in `tool-config.ts` already correctly reads
circuit breaker config from `argus.config.yaml` (lines 71-75). Only Python is broken.

---

### Item 2: scan-store.ts positional phase indexing

**Status:** ⚠️ Partially addressed in event handler, latent bug in addPhase/completePhase
**Files:** `Argus-Tui/packages/opencode/src/argus/tui/scan-store.ts`,
`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`

**Problem:**
- `completePhase()` takes a positional `index` (line 122)
- `addPhase()` appends at `scanState.phases.length` (line 113)
- Replan appends phases to `plan.phases` via `push()` — works today because
  replan is append-only, but any future mid-array insertion breaks index alignment
- `phaseRecords[]` in `workflow-runner.ts` is array-indexed; if replanning ever
  inserts mid-array, `phaseRecords[i]` would point to the wrong record

**Fix:**
1. **`scan-store.ts`:** Refactor `addPhase()` to accept `phaseId` and check for
   existing phase first via `findPhaseIndex()`. Refactor `completePhase()` to
   accept `phaseId` and resolve via `findPhaseIndex()`. Update `processEventInner()`
   to call the ID-based versions.

2. **`workflow-runner.ts`:** Convert `phaseRecords[]` to
   `Map<string, PhaseRecord>` for O(1) lookup plus `phaseOrder: string[]` for
   execution ordering. All access goes through `phaseRecords.get(phaseId)`.

**Effort:** ~45 minutes (15 lines in scan-store.ts + 30 lines in workflow-runner.ts)

---

### Item 3: `cost` field is dead metadata

**Status:** ✅ Valid — `selectBest()` ignores `cost`
**Files:** `Argus-Tui/packages/opencode/src/argus/workflows/tool-registry.ts`,
`Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml`

**Problem:**
`ToolDef` declares `cost?: "low" | "medium" | "high"` (line 33) and all 65 Python
YAMLs have `cost:` populated, but the TS `tool-definitions.yaml` only has `cost`
on agent-internal tools (lines 720-900). External scanners (nuclei, sqlmap, nmap,
dalfox, etc.) have no `cost` field in the TS YAML. `selectBest()` ranks purely by
`confidence_score + coverage_score` then `priority` — `cost` is never examined.

**Fix (Branch C — plumbing only, no UX):**
1. Add `cost` to all ~50 external scanner tools in `tool-definitions.yaml` by
   copying values from the Python YAMLs.
2. Add `costFilter?: "all" | "low_only" | "no_high"` parameter to `selectBest()`,
   defaulting to `"all"` (no behavior change).
3. When `costFilter !== "all"`, filter candidates before sorting. If a capability
   would have zero tools after filtering, keep the unfiltered set for that cap
   (safety: never leave a capability uncovered).
4. In `planner.ts`, when loading the `quick_scan` workflow, pass `costFilter: "no_high"`
   internally. This makes the existing (but currently dead) `quick_scan.yaml` functional.
5. Optionally in `planner.ts` `PlanOptions`, accept `costFilter?: CostFilter`.

**Cost values for `tool-definitions.yaml`:**

| Tools | Cost | Rationale |
|-------|------|-----------|
| `nuclei` | `medium` | Fast but template-heavy |
| `nmap`, `naabu`, `ffuf`, `katana`, `gospider`, `arjun` | `medium` | Network intensive |
| `nikto`, `dalfox`, `wpscan`, `trivy`, `gitleaks` | `medium` | Moderate runtime |
| `sqlmap`, `commix`, `masscan`, `sn1per` | `high` | Destructive / very noisy |
| `amass` | `medium` | Long-running DNS enumeration |
| `httpx`, `whatweb`, `subfinder`, `dnsx`, `gau`, `waybackurls` | `low` | Fast, lightweight |
| `semgrep`, `bandit`, `gosec`, `brakeman`, `spotbugs` | `low` | Local file analysis |
| `testssl`, `wafw00f`, `jwt_tool` | `low` | Targeted, quick |
| All agent-internal tools | `low` | Already set in TS YAML |

**Effort:** ~1-2 hours (multi-file but well scoped)

---

### Item 4: `version_cmd` / `min_version` / `version_regex` missing from TS YAML

**Status:** ❌ Misstated in original plan — fields **do not exist** in any YAML file.
Corrected scope: add them as a new feature, not fix dead code.
**Files:** `Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml`,
`Argus-Tui/packages/opencode/src/argus/workflows/tool-registry.ts`,
`Argus-Tui/packages/opencode/src/argus/commands/doctor.ts`

**Problem:**
`doctor.ts` has a hardcoded `TOOL_VERSION_CHECKS` array (lines 459-480) for 12
tools. The `ToolDef` interface doesn't declare `version_cmd`, `min_version`, or
`version_regex`. Only `nuclei` in the TS `tool-definitions.yaml` has these fields
(lines 14-16). This duplicates tool metadata in two places — the YAML and the
hardcoded array.

**Fix:**
1. Add `version_cmd?: string`, `min_version?: string`, `version_regex?: string`
   to the `ToolDef` interface in `tool-registry.ts`.
2. Add these fields to `tool-definitions.yaml` for the 12 tools the doctor
   currently tracks, matching the values in `TOOL_VERSION_CHECKS`:

| Tool | `version_cmd` | `min_version` | `version_regex` |
|------|---------------|---------------|-----------------|
| nuclei | `nuclei --version` | `3.0.0` | `\d+\.\d+\.\d+` |
| nmap | `nmap --version` | — | `\d+\.\d+` |
| nikto | `nikto -Version` | — | `\d+\.\d+\.\d+` |
| whatweb | `whatweb --version` | — | `\d+\.\d+\.\d+` |
| ffuf | `ffuf -V` | — | `\d+\.\d+` |
| httpx | `httpx -version` | — | `\d+\.\d+\.\d+` |
| subfinder | `subfinder -version` | — | `\d+\.\d+\.\d+` |
| dalfox | `dalfox version` | — | `\d+\.\d+\.\d+` |
| gitleaks | `gitleaks version` | — | `\d+\.\d+\.\d+` |
| trivy | `trivy --version` | — | `\d+\.\d+\.\d+` |
| semgrep | `semgrep --version` | — | `\d+\.\d+\.\d+` |
| katana | `katana -version` | — | `\d+\.\d+\.\d+` |

3. Refactor `doctor.ts` `toolchainCheck()` (line 500) to build `versionCheckMap`
   from the tool registry instead of the hardcoded `TOOL_VERSION_CHECKS` array.
   Remove the `TOOL_VERSION_CHECKS` array.

**Effort:** ~1-2 hours

---

## Week 2 — Priority 2 + Data Residency Subproject (a) Bundled

### Item 5: N+1 queries in workspace.tsx

**Status:** ✅ Valid
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

**Status:** ✅ Valid
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

**Status:** ✅ Valid
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

**Status:** ✅ Bundled with Week 2
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

**Status:** ✅ Valid — plus critical prerequisite bug found
**Files:** `argus-workers/tools/definitions/playwright-bola.yaml`,
`argus-workers/tools/scripts/playwright_bola.py`,
`Argus-Tui/packages/opencode/src/argus/workflows/tool-registry.ts`,
`Argus-Tui/packages/opencode/src/argus/planner/executor.ts`,
`argus-workers/mcp_server.py`

**Prerequisite bug — must fix first:**
The YAML declares individual credential params (`--attacker-username`,
`--attacker-password`, etc.) but `playwright_bola.py` accepts `--creds-file`
(a path to a JSON file with `{"attacker": {...}, "victim": {...}}`). The YAML
and the Python script **don't match**. Every call to `playwright-bola` will
fail with "unrecognized arguments."

**Fix the mismatch:**
Align the YAML to match the Python script: replace the 4 credential params
with a single `--creds-file` param.

**Add credential role support:**
1. Add `credential_roles?: string[]` field to the YAML and to `ToolDef` interface.
2. Wire `requires: { credentials: true }` into `passesGates()` — currently dead.
3. Add `availableCredentialRoles` and `hasAnyCredentials` to `GateContext`.
4. Add `resolveToolCredentials(toolName, credentials)` method in `executor.ts`
   that reads the tool's declared `credential_roles`, looks up each role from
   `CredentialStore`, writes them to a temp file (mode 0o600), and returns the path.
5. Add `credential_roles` to Python `ToolDefinition.__init__` and `to_dict()` (~3 lines).

**Effort:** ~2 hours (includes fixing the YAML/Python mismatch)

---

### Item 11: No proactive DNS validation

**Status:** ✅ Valid
**Files:** `argus-workers/mcp_server.py`, `Argus-Tui/packages/opencode/src/argus/commands/doctor.ts`

**Problem:**
DNS-reliant tools (subfinder, amass, dnsx) silently fail when DNS is broken
inside the container. No pre-flight check exists.

**Fix:**
1. In `mcp_server.py` startup sequence, add:
```python
import socket
try:
    socket.getaddrinfo("dns.google", 53)
except socket.gaierror:
    logger.warning("DNS resolution failed — DNS-reliant tools may not work. "
                   "Check container DNS config or set --dns-servers 8.8.8.8")
```
2. In `doctor.ts`, add a DNS check to the `toolchainCheck()` or as a new check.
3. Wire the warning into `doctor` command output.

**Effort:** ~30 minutes

---

## Week 4 — Priority 3 (Requires Testing Against Real Targets)

### Item 9: No global rate limit / concurrency cap

**Status:** ✅ Valid — with corrected primitive
**Files:** `argus-workers/runtime/concurrency.py` (new),
`argus-workers/tools/tool_runner.py`

**Problem:**
`MAX_CONCURRENT_REQUESTS = 20` is defined in `config/constants.py` (line 260)
but **never consumed**. Independent `ThreadPoolExecutor` instances spawn
unbounded concurrent subprocesses across Celery workers: recon uses 8 workers,
scan uses 5, web_scanner uses 6, etc. With Celery concurrency=8, worst case
is ~120 concurrent subprocesses.

**Fix:**
1. Create `runtime/concurrency.py`:
```python
import threading
from config.constants import MAX_CONCURRENT_REQUESTS

SUBPROCESS_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

HIGH_COST_TOOLS = {"sqlmap", "dalfox", "commix", "nuclei", "masscan", "sn1per"}
HIGH_COST_SEMAPHORE = threading.BoundedSemaphore(
    max(1, MAX_CONCURRENT_REQUESTS // 3)
)
```

2. In `tool_runner.py` `run()` and `run_streaming()`, acquire the appropriate
   semaphore before calling `subprocess.run()` / `subprocess.Popen()`.

3. TS side left unchanged — `MAX_PARALLEL_TOOLS = 4` per phase is sufficient
   since phases run sequentially.

**Note:** A Redis-based token bucket would be needed for multi-host distributed
deployment. Document this as a future enhancement in code comments.

**Effort:** ~20 lines, but needs testing against real targets in Week 4

---

### Item 10: Docker networking — container can't reach localhost targets

**Status:** ✅ Valid
**Files:** `docker-compose.yml`, `README.md`

**Problem:**
The `worker` service in `docker-compose.yml` (lines 80-99) is on the default
bridge network. `localhost` inside the container means the container itself,
not the host. macOS/Windows get `host.docker.internal` automatically, but
Linux does not.

**Fix:**
1. Add to the `worker` service in `docker-compose.yml`:
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```
2. Document in README that when testing against localhost targets, use
   `host.docker.internal` as the hostname.
3. Optionally add a `HOST_NETWORK=1` compose override:
```yaml
# docker-compose.override.yml
services:
  worker:
    profiles: ["host-network"]
    network_mode: host
```

**Effort:** ~15 minutes for compose + ~30 minutes for docs

---

## Ongoing (Parallel with Other Work)

### Item 12: Air-gap / offline mode in Dockerfile

**Status:** ✅ Valid
**Files:** `argus-workers/Dockerfile`, `README.md`

**Problem:**
The Dockerfile unconditionally fetches: Go tarball (line 19), Go tools (lines
28-37), pip deps (line 41), sqlmap (line 48). No `ARG AIRGAP`.

**Fix:**
1. Add `ARG AIRGAP=0` at the top of the Dockerfile.
2. Wrap each internet fetch step:
```dockerfile
RUN if [ "$AIRGAP" = "0" ]; then \
      curl -fsSL "https://go.dev/dl/..." -o /tmp/go.tar.gz && ...; \
    fi
```
3. For air-gap builds, expect tools pre-copied into `./vendor/` directory.
4. Document:
```bash
# Standard build:
docker build -t argus .

# Air-gap build (pre-populate ./vendor/ first):
docker build --build-arg AIRGAP=1 -t argus-airgap .
```

**Effort:** ~1 hour Dockerfile + ~30 minutes docs

---

### Item 13: `allowed_git_hosts: []` allow-all semantics

**Status:** ⚠️ Behavioral mismatch between TS and Python
**Files:** `argus.config.yaml`, `argus-workers/config/constants.py`,
`Argus-Tui/packages/opencode/src/argus/shared/target-validator.ts`,
`Argus-Tui/packages/opencode/src/argus/config/loader.ts`

**Problem:**
- **TS side** (`target-validator.ts:162-177`): empty list = allow all (documented
  as backward-compatible default)
- **Python side** (`constants.py:93-130`): hardcoded 13-host allowlist (github.com,
  gitlab.com, etc.) that can only be extended via env var, never replaced
- `argus.config.yaml` line 18: `allowed_git_hosts: []` — no `git_host_policy` field

**Fix (Option b):**
1. Add `scope.git_host_policy: "allowlist" | "allow_all"` to `argus.config.yaml`:
```yaml
scope:
  # When "allowlist", only hosts in allowed_git_hosts (or the default curated list)
  # are permitted. When "allow_all", all git hosts pass through.
  # Default: "allowlist" with a curated default list.
  git_host_policy: "allowlist"
  allowed_git_hosts: []
```
2. Add `GitSSRFConfig.from_config()` method that reads `argus.config.yaml`
   and respects `git_host_policy`. When `"allow_all"`, set `host_allowlist=()`.
3. Add `ScopeConfigSchema` to the TS Zod schema in `config/loader.ts`.
4. TS side surfaces the policy for UI — Python enforces it at runtime.
5. Update comment in `target-validator.ts` to note the dual enforcement.

**Effort:** ~1 hour

---

### Subproject 14(b): Per-engagement storage isolation

**Status:** After 14(a) is merged
**Files:** Storage layer (`store.ts`, `storage/paths.ts`)

**Problem:**
All data lives in a single `argus.db` SQLite file. No per-engagement directory
isolation.

**Fix:**
Reorganize storage to:
```
~/.argus/
├── argus.db              ← engagement index (metadata only)
└── engagements/
    ├── ENG-abc123/
    │   ├── engagement.db  ← findings, evidence, audit log
    │   └── evidence/      ← binary evidence files
    └── ENG-def456/
        ├── engagement.db
        └── evidence/
```

`StoragePaths.engagementDir()` and `StoragePaths.engagementDbPath()` from
subproject 14(a) provide the path utilities. The store creates a per-engagement
DB on first access and stores only engagement metadata in the root DB.

**Effort:** A few days

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
  Item 1  (Circuit breaker)     ─ 5 min
  Item 2  (Phase indexing)      ─ 45 min
  Item 3  (Cost metadata)       ─ 1-2 hrs
  Item 4  (Version fields)      ─ 1-2 hrs
  ─── Total: ~1 day ───

Week 2 ──────────────────────────────────────
  Item 5  (N+1 queries)         ─ 30 min
  Item 6  (4 DB queries)        ─ 1 hr
  Item 7  (Audit log filter)    ─ 30 min
  14(a)   (Configurable paths)  ─ 1 afternoon
  ─── Total: ~1.5 days ───

Week 3 ──────────────────────────────────────
  Item 8  (Playwright creds)    ─ 2 hrs (fixes YAML/Python mismatch too)
  Item 11 (DNS validation)      ─ 30 min
  ─── Total: ~0.5 day ───

Week 4 ──────────────────────────────────────
  Item 9  (Rate limiting)       ─ 20 min code + testing
  Item 10 (Docker networking)   ─ 45 min
  ─── Total: ~0.5 day ───

Ongoing ─────────────────────────────────────
  Item 12 (Air-gap)             ─ 1.5 hrs
  Item 13 (Git host policy)     ─ 1 hr
  14(b)   (Engagement isolation) ─ few days
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
