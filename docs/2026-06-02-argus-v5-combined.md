# Argus V5 Design & Architecture Plan

**Date:** 2026-06-02
**Status:** Approved Design — with remediation tasks from backend codebase review

---

## Table of Contents

1. [Vision](#1-vision)
2. [Success Criteria](#2-success-criteria)
3. [Architecture](#3-architecture)
4. [Decision Tree (20 Resolved Decisions)](#4-decision-tree-20-resolved-decisions)
5. [Component Specifications](#5-component-specifications)
    - 5.7 [Workflow Registry](#57-workflow-registry-srcargusworkflows)
    - 5.8 [Tool Capability Registry](#58-tool-capability-registry)
    - 5.9 [Engagement State Store](#59-engagement-state-store-srcargusengagement)
    - 5.10 [Human Approval Gates](#510-human-approval-gates)
6. [Architecture Review (V5 TypeScript Fork)](#6-architecture-review-v5-typescript-fork)
7. [Backend Codebase Review (argus-workers Python Engine)](#7-backend-codebase-review-argus-workers-python-engine)
8. [Consolidated Implementation Tasks](#8-consolidated-implementation-tasks)
9. [Dependency Analysis](#9-dependency-analysis)
10. [Rollback Strategy](#10-rollback-strategy)
11. [ADRs to Create](#11-adrs-to-create)

---

## 1. Vision

```
Reason → Plan → Execute → Observe → React → Verify → Capture Evidence → Report
```

Argus V5 is a fork of [OpenCode](https://github.com/anomalyco/opencode) with cybersecurity superpowers. The TypeScript CLI (forked from OpenCode) provides the runtime foundation, provider-agnostic LLM access, TUI, and session management. Argus-specific modules add autonomous security workflows, browser-based verification, evidence collection, and professional reporting. Existing Python workers (`argus-workers/`) are accessed via the MCP protocol for tool execution.

**Assessment lifecycle:**

```text
/assess <target>
  → plan          (detect target type → select workflow → resolve tools)
  → execute phase (run phase with LLM or deterministic fallback)
  → collect       (artifacts, evidence, screenshots)
  → evaluate      (ConfidenceEngine.promote() on findings)
  → replan        (determineNewCapabilities() → insert new phases if needed)
  → [next phase]  (repeat execute → collect → evaluate → replan)
  → finalize      (mark findings as FINALIZED, snapshot workflow)
  → report        (re-query SQLite → generate output)
```

---

## 2. Success Criteria

1. Use OpenCode as the runtime foundation.
2. Remain provider-agnostic.
3. Plan security workflows autonomously.
4. Orchestrate multiple security tools.
5. Dynamically interact with web applications.
6. Observe and react to application behavior.
7. Verify findings automatically.
8. Capture evidence for every confirmed finding.
9. Generate professional reports.
10. Fall back to deterministic execution when AI is unavailable.

---

## 3. Architecture

```
argus/                               # Monorepo root
├── cli/                             # OpenCode fork (TypeScript)
│   ├── src/
│   │   ├── index.ts                 # Entry point
│   │   ├── providers/               # OpenCode — kept as-is
│   │   ├── sessions/                # OpenCode — kept as-is
│   │   ├── agent/                   # OpenCode — kept as-is
│   │   ├── tui/                     # OpenCode — kept as-is
│   │   ├── streaming/               # OpenCode — kept as-is
│   │   ├── config/                  # OpenCode — kept as-is
│   │   │
│   │   └── argus/                   # NEW — Argus-specific modules
│   │       ├── planner/             # Workflow planning (LLM + deterministic)
│   │       ├── browser/             # Observe & React (Playwright)
│   │       ├── evidence/            # Artifact collection
│   │       ├── reporting/           # Professional reports
│   │       ├── bridge/              # MCP client → Python workers
│   │       ├── workflows/           # YAML workflow definitions (Gap 1)
│   │       ├── engagement/          # Assessment state store (Gap 4)
│   │       └── commands/            # Security CLI commands
│   ├── package.json
│   └── tests/
│
├── argus-workers/                   # EXISTING — Python, with remediation
│   ├── mcp_server.py                # MCP protocol server
│   ├── mcp_transport.py             # NEW — stdio JSON-RPC transport (Task 0.1)
│   ├── tools/                       # 28 security tool wrappers
│   ├── agent/                       # ReAct agent
│   ├── llm_client.py                # Unified LLM client
│   ├── cache.py                     # Redis cache (extended for CVE/EPSS)
│   ├── intelligence_engine.py       # Decision core (with CVE caching)
│   ├── state_machine.py             # Engagement state machine (connection fix)
│   ├── database/
│   │   ├── connection.py            # Connection pool (busy-wait fix)
│   │   └── ...
│   └── ...
│
├── ARCHITECTURE_BOUNDARIES.md
├── argus.db                        # SQLite (WAL mode): engagements, findings, evidence (auto-created)
└── Makefile
```

### 3.1 Fork Boundary Enforcement

Argus is a controlled-divergence fork of OpenCode. To prevent architectural erosion, a strict import boundary is enforced between Argus modules and OpenCode internals.

**Rule:** Argus modules (`src/argus/`) may depend only on symbols exported from designated public runtime entry points. Direct imports into OpenCode implementation files or subdirectories are prohibited — regardless of directory location or naming convention.

```typescript
// ✅ ALLOWED — public runtime contracts only
import { IProviderManager, ISessionStore, IRuntimeEvents, ICommandRegistry }
  from "@opencode/runtime";

// ❌ PROHIBITED — bypasses public API, couples to file layout
import { Provider } from "../../opencode/providers/provider";
import { SessionManager } from "../../opencode/sessions/manager";
import { KeyBindings } from "../../opencode/tui/keybindings";
```

**Enforcement** (ESLint rule in `cli/.eslintrc.json`):

```json
{
  "no-restricted-imports": ["error", {
    "patterns": [
      "../../opencode/*",
      "../opencode/*",
      "**/opencode/providers/*",
      "**/opencode/sessions/*",
      "**/opencode/tui/*",
      "**/opencode/agent/*",
      "**/opencode/streaming/*"
    ]
  }]
}
```

**Rationale:** This is Option 2 (export-boundary enforcement). Option 1 (directory-based) is too loose — directories mix public contracts and implementations. Option 3 (naming-based) is too ambiguous — names drift. Only a public-API-based boundary is enforceable, testable, and maintainable as the upstream codebase evolves. When OpenCode refactors internals, Argus modules continue to compile unchanged because they depend only on the stable runtime interface surface.

**Recommended reading:** `ARCHITECTURE_BOUNDARIES.md` (Task 1.3) will contain the full contract.

### 3.2 Configuration Hierarchy

Argus has multiple configuration sources. A single precedence rule governs all of them:

```text
CLI flags > Environment variables > Project config > User config > Built-in defaults
```

| Source | Location | Example |
|--------|----------|---------|
| **CLI flags** (highest) | Command-line invocation | `--creds ./creds.json` |
| **Environment variables** | Shell environment | `ARGUS_WORKERS_PATH`, `ARGUS_PYTHON`, `ARGUS_ALLOWED_GIT_HOSTS` |
| **Project config** | `./argus.config.yaml` (per-repo, committed) | `evidence.retention_days: 90` |
| **User config** | `~/.argus/config.yaml` (machine-local, not committed) | `evidence.retention_days: 30` |
| **Built-in defaults** (lowest) | Code constants | `evidence.retention_days: 30` |

**Merge rules:**

- Scalars: highest-priority source wins.
- Objects: deep-merge across sources (lower-priority keys survive if not overridden).
- Arrays: replace semantics — highest-priority source wins entirely.
- Feature flags: live in project config, overridable by CLI/env for testing.

**Workflow YAMLs** (`workflows/*.yaml`) are **not** in this hierarchy. They define the assessment plan (phases, capabilities, execution mode), not runtime configuration. The workflow YAML is versioned and snapshotted per engagement; runtime config is resolved at startup.

**Enforcement:**

```typescript
// Internal — every resolved value tracks its origin
interface ResolvedValue<T> {
  value: T;
  source: "cli" | "env" | "project_config" | "user_config" | "default";
}

// Merged config is validated once at startup before assessment execution
const config = await ConfigLoader.load();  // throws on invalid merged config
```

**Commands:**

| Command | Behavior |
|---------|----------|
| `/config` | Prints effective resolved configuration with source annotations |
| `/doctor` | Validates merged config as part of runtime checks |

---

## 4. Decision Tree (20 Resolved Decisions)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Repository layout | Monorepo `cli/` | Single git clone, one CI, simple versioning |
| 2 | Fork approach | True git fork of OpenCode | Upstream cherry-picks, OpenCode's complete infra |
| 3 | MCP transport | Subprocess stdio | Zero config, natural deterministic fallback |
| 4 | Workers discovery | Relative `../argus-workers/` → `ARGUS_WORKERS_PATH` → deterministic | Works out of the box, fallback for custom installs |
| 5 | Planner mode | Hybrid: LLM via OpenCode providers + deterministic regex fallback | Satisfies criteria #3 (autonomous) and #10 (fallback) |
| 6 | Browser scope | BOLA + Stored XSS + Privilege Escalation (DOM XSS deferred) | Three workflows that genuinely need a browser |
| 7 | Destructive tools | Prompt in interactive mode, skip in `--auto` mode | Safe autonomy |
| 8 | Evidence capture | Automatic during every verification | Satisfies criterion #8 |
| 9 | Report timing | Auto after `/assess` + manual `/report` | Most complete UX |
| 10 | Output style | Real-time streaming per phase | Builds user confidence during long scans |
| 11 | Feature flags | All V5 disabled by default (opt-in) | v5 behaves identically to v4 until configured |
| 12 | Installation | `npm install -g argus` | Simplest path, matches OpenCode pattern |
| 13 | CI/CD | GitHub Actions: lint → typecheck → unit → integration | Quality gate before every merge |
| 14 | E2E targets | Juice Shop + crAPI + DVWA + VAmPI | Full coverage of web + API vulnerability types |
| 15 | Python CLI | Removed after TypeScript CLI is stable | One CLI, one install path |
| 16 | Workflow registry | YAML files in `workflows/` dir, loaded by planner | Decouples workflow logic from code; new workflows without code changes |
| 17 | Confidence model | 6-level `Confidence` enum from INFORMATIONAL to CONFIRMED | Enables report quality scoring and automated triage |
| 18 | Engagement state store | Filesystem `~/.argus/engagements/` with JSON state | Enables resume/replay; decouples state from memory and reports |
| 19 | Human approval gates | YAML config per workflow; prompt in interactive, skip in `--auto` | Safe autonomy for destructive and auth-testing workflows |
| 20 | Multi-agent expansion | ADR-008 reserved; future planner/recon/verification/report agents | Prevents today's decisions from blocking tomorrow's architecture |
 
---

## 5. Component Specifications

### 5.1 Planner (`src/argus/planner/`)

**Purpose:** Determine target type → required capabilities → select workflow → select tools by capability.

**Files:**

| File | Responsibility |
|------|---------------|
| `types.ts` | `TargetType`, `AuthState`, `Workflow`, `AssessmentPlan`, `Capability`, `PlannerContext` types |
| `capabilities.ts` | Canonical `Capability` enum — single source of truth; every capability used in YAML must appear here. Enum values only, never free-form strings. |
| `strategy.ts` | `detectTargetType(url, techStack?)`, `determineRequiredCapabilities(targetType, authState, techStack, findings?)` → `Capability[]` |
| `planner.ts` | `WorkflowPlanner.plan(target, context)` — capability-driven; supports `replan(context)` with cycle prevention. Returns fully serializable `AssessmentPlan`. |
| `planDeterministic.ts` | `planDeterministic(target)` — regex-based fallback when LLM is unavailable |
| `replan-rules.ts` | `determineNewCapabilities(context)` — deterministic rules engine over normalized findings. LLM classifies/enriches, but phase insertion decisions are always deterministic and enum-bound. |
| `executor.ts` | `PhaseExecutor` interface + `InProcessExecutor` implementation — v5 runs phases in-process, but the interface enables remote executors in v6 without changing planner logic. |

**Multi-agent ready contracts** (defined in `types.ts`):

```typescript
// Fully serializable — JSON-safe, no function references, no runtime objects.
// Planner and executor communicate only through these objects, never shared mutable state.

interface PhaseExecutionRequest {
  phaseId: string;
  workflowName: string;
  target: string;
  requiredCapabilities: Capability[];
  credentials?: CredentialRef[];         // Roles needed, resolved by CredentialStore
  config: Record<string, unknown>;       // Tool config, timeouts, thresholds
  previousPhaseResults: PhaseExecutionResult[];
}

interface PhaseExecutionResult {
  phaseId: string;
  status: "completed" | "failed" | "skipped" | "partial";
  findings: NormalizedFinding[];
  artifacts: ArtifactRef[];
  errors: string[];
  durationMs: number;
}

interface AssessmentPlan {
  workflow: string;
  phases: PhaseExecutionRequest[];        // Ordered, each with unique phaseId
  errorRecovery: Record<string, ErrorRecovery>;
  planCreatedAt: string;
}
```

**Executor interface** (defined in `executor.ts`):

```typescript
interface PhaseExecutor {
  execute(phase: PhaseExecutionRequest): Promise<PhaseExecutionResult>;
}

// v5 implementation — in-process, same runtime
class InProcessExecutor implements PhaseExecutor {
  execute(phase: PhaseExecutionRequest): Promise<PhaseExecutionResult> {
    // Resolves tools via ToolRegistry, runs them, collects results
    // Calls ConfidenceEngine.promote() on findings
    // Gathers artifacts into EvidenceCollector
  }
}
```

This design defers the multi-agent architecture to v6 without constraining today's code. The planner produces `PhaseExecutionRequest` objects; the `PhaseExecutor` interface hides whether execution is in-process (v5) or delegated to a remote agent (v6+). No planner logic changes when the executor is swapped.

**Canonical Capability enum** (defined in `capabilities.ts`):

```typescript
export enum Capability {
  WEB_RECON = "web_recon",
  PORT_SCANNING = "port_scanning",
  TECHNOLOGY_DETECTION = "technology_detection",
  CONTENT_DISCOVERY = "content_discovery",
  API_PROBING = "api_probing",
  AUTH_DETECTION = "auth_detection",
  CREDENTIAL_ANALYSIS = "credential_analysis",
  VULNERABILITY_SCANNING = "vulnerability_scanning",
  TEMPLATE_SCANNING = "template_scanning",
  BROWSER_VERIFICATION = "browser_verification",
  REPORT_GENERATION = "report_generation",
  SQLI_DETECTION = "sqli_detection",
  DATABASE_EXFILTRATION = "database_exfiltration",
  HTTP_PROBE = "http_probe",
  GRAPHQL_ASSESSMENT = "graphql_assessment",
  EXPRESS_CVE_SCAN = "express_cve_scan",
  API_DOCS_ANALYSIS = "api_docs_analysis",
  JWT_ANALYSIS = "jwt_analysis",
  SSRF_CHECK = "ssrf_check",
}
```

This enum is the single source of truth. The YAML loader (`loader.ts`) validates every `required_capabilities` entry against this enum at load time. A capability not in the enum causes a hard validation error — no silent planner drift.

**PlannerContext:**

```typescript
interface PlannerContext {
  target: string;
  targetType: TargetType;
  authState: AuthState;
  techStack?: string[];
  findings: Finding[];                         // Accumulated across phases; feeds replan()
  executedCapabilities: Set<Capability>;        // Prevents re-inserting already-run phases
  insertedPhases: Set<string>;                  // Phase names added by replan — prevents duplicates
  replanCount: number;                          // Incremented on every replan call
}

> **Serialization boundary:** `PlannerContext` is an **in-memory runtime object only** — it is never serialized directly. `Set<Capability>` and `Set<string>` fields are not JSON-safe by design, which is intentional: they are transient runtime constructs. On engagement resume, `PlannerContext` is reconstructed from SQLite rows: `executedCapabilities` is built from `SELECT DISTINCT capability FROM completed_phases WHERE engagement_id = ?`, `findings` from `SELECT * FROM findings WHERE engagement_id = ?`, and `replanCount` from `SELECT COUNT(*) FROM phase_results WHERE engagement_id = ? AND replan_cycle = true`. The persistent SQLite representation uses `string[]` arrays; the runtime representation uses `Set` for O(1) membership checks. These two representations are cleanly separated by the load/save boundary in `EngagementStore`.

**Replan cycle prevention:**
}
```

**Replan cycle prevention:**

```typescript
const MAX_REPLANS = 10;

function replan(context: PlannerContext): Phase[] | null {
  if (context.replanCount >= MAX_REPLANS) {
    return null;  // Hard limit — stop inserting new phases
  }

  const newCapabilities = determineNewCapabilities(context);
  // Filter out capabilities already executed or already inserted
  const unhandled = newCapabilities
    .filter(c => !context.executedCapabilities.has(c));

  if (unhandled.length === 0) return null;

  context.replanCount++;
  return createPhasesForCapabilities(unhandled);
}
```

This prevents infinite planning loops. The `executedCapabilities` set ensures the same capability is never executed twice. The `insertedPhases` set prevents duplicate phase names. The `MAX_REPLANS` hard cap stops runaway replanning on noisy targets.

**`determineNewCapabilities()` — deterministic rules engine** (defined in `replan-rules.ts`):

```typescript
// Input: normalized findings from completed phase
// Output: set of new Capability enum values to insert
// The LLM may enrich/classify raw findings into normalized form,
// but the replan decision itself is always deterministic.

function determineNewCapabilities(context: PlannerContext): Set<Capability> {
  const result = new Set<Capability>();

  for (const finding of context.findings) {
    // Rules are pattern-matched on normalized finding type/subtype
    switch (finding.subtype) {
      case "graphql":
        result.add(Capability.GRAPHQL_ASSESSMENT);
        break;
      case "expressjs":
        result.add(Capability.EXPRESS_CVE_SCAN);
        break;
      case "swagger":
      case "openapi":
        result.add(Capability.API_DOCS_ANALYSIS);
        break;
      case "jwt":
        result.add(Capability.JWT_ANALYSIS);
        break;
      case "ssrf_parameters":
        result.add(Capability.SSRF_CHECK);
        break;
    }
  }

  // Finite universe — only capabilities in the enum can be returned
  // Insert-once — calling code filters against executedCapabilities
  // Hard limit — calling code enforces MAX_REPLANS
  return result;
}
```

> **Capability classification:** Not all `Capability` enum members are candidates for dynamic insertion. The table below documents which capabilities appear in the initial plan only and which can be inserted via replan. An empty replan-insertable set means the capability is always determined at initial workflow selection time and never added mid-assessment.
>
> | Capability | Initial plan | Replan-insertable | Trigger |
> |---|---|---|---|
> | `WEB_RECON`, `PORT_SCANNING`, `TECHNOLOGY_DETECTION`, `CONTENT_DISCOVERY` | Yes | No | Always in initial recon phase |
> | `API_PROBING`, `AUTH_DETECTION`, `CREDENTIAL_ANALYSIS` | Yes | No | Always in initial auth/detection phase |
> | `VULNERABILITY_SCANNING`, `TEMPLATE_SCANNING`, `HTTP_PROBE` | Yes | No | Always in initial vuln scan phase |
> | `BROWSER_VERIFICATION` | Yes | No | Always in initial verification phase |
> | `REPORT_GENERATION` | Yes | No | Always final phase |
> | `GRAPHQL_ASSESSMENT` | No | Yes | finding.subtype === "graphql" |
> | `EXPRESS_CVE_SCAN` | No | Yes | finding.subtype === "expressjs" |
> | `API_DOCS_ANALYSIS` | No | Yes | finding.subtype === "swagger" or "openapi" |
> | `JWT_ANALYSIS` | No | Yes | finding.subtype === "jwt" |
> | `SSRF_CHECK` | No | Yes | finding.subtype === "ssrf_parameters" |
> | `SQLI_DETECTION`, `DATABASE_EXFILTRATION` | No | Yes | finding.subtype === "sqli_reflective" or "sqli_blind" |
>
> This classification ensures that the `determineNewCapabilities()` switch statement is intentionally incomplete: only replan-insertable capabilities need cases. All others are guaranteed to never appear from replan logic. If a new capability is added to the enum, it must be added to one of these two groups — there is no third option.

**Three independent termination safeguards:**

| # | Safeguard | Mechanism | Enforced by |
|---|-----------|-----------|-------------|
| 1 | **Finite capability universe** | `Capability` enum with ~30-50 members. Rules can only return enum values — never free-form strings. | TypeScript compiler + YAML loader validation |
| 2 | **Insert-once semantics** | `executedCapabilities: Set<Capability>` + `insertedPhases: Set<string>` prevent a capability or phase from being added twice, even if discovered repeatedly. | `replan()` filter logic |
| 3 | **Hard replan limit** | `MAX_REPLANS = 10`. After 10 replan cycles the planner returns `null` unconditionally. | `replan()` guard clause |

The LLM participates only in **classification/enrichment** — e.g., detecting "Apollo GraphQL" from raw HTTP and normalizing it into `Finding(type: "technology", subtype: "graphql")`. The phase insertion decision itself remains a deterministic rule over enum-bound capabilities. This keeps `replan()` auditable, testable, and provably terminating.

**Planning pipeline:**

```text
Target URL
  → detectTargetType() → { web_app | api | spa | unknown }
  → determineRequiredCapabilities(targetType, findings?) → [web_recon, content_discovery, ...]
  → WorkflowRegistry.findByCapabilities(required) → best matching workflow
  → For each phase: ToolRegistry.getToolsByCapability(phase.required_capabilities)
  → AssessmentPlan { workflow, phase_tool_mapping, error_recovery }
  → After each phase: findings → PlannerContext → replan() if new capabilities needed
```

This is the primary path. Workflows define **what** needs to happen (capabilities), not **which** tools to use. Tool selection is deferred to the registry, which considers tool availability, target type, and auth state.

**Built-in workflows:**

| Workflow | Phases (required capabilities) | Target |
|----------|--------------------------------|--------|
| `full_assessment` | recon → auth_detection → api_discovery → vuln_scan → verification → reporting | Web apps |
| `api_assessment` | recon → auth_detection → api_discovery → bola_testing → verification → reporting | APIs |
| `quick_scan` | recon → vuln_scan → reporting | Passive/no-LLM mode |
| `browser_assessment` | recon → browser_scan → auth_detection → verification → reporting | SPAs |

**Phase capability example:**

```yaml
# In workflow YAML (workflows/full_assessment.yaml)
phases:
  - name: recon
    required_capabilities:
      - web_recon
      - port_scanning
      - technology_detection
    execution: parallel          # Concurrent tool execution within phase
  - name: vuln_scan
    required_capabilities:
      - vulnerability_scanning
      - template_scanning
    execution: parallel
```

The planner never references tool names. It asks: "which tools provide `web_recon`?" The registry answers. Each phase's `execution` mode tells the runner whether tools in that phase should run concurrently (`parallel`) or one at a time (`sequential`).

**Fallback:** When LLM unavailable, `planDeterministic()` uses URL regex patterns (`/api/`, `.json`, known SPA tech) to determine target type and required capabilities, then selects the closest workflow via the same capability-matching path.

### 5.2 MCP Bridge (`src/argus/bridge/`)

**Purpose:** IPC between TypeScript CLI and Python workers.

**Files:**

| File | Responsibility |
|------|---------------|
| `mcp-client.ts` | `WorkersBridge.connect()`, `callTool()`, `getTools()` |
| `types.ts` | `ToolResult`, `ToolDefinition`, `MCPError` types |
| `supervisor.ts` | `WorkerSupervisor` — monitors child process health, restarts on crash, tracks restart count |

**Transport:**
- Spawn `python3 <workers-path>/mcp_server.py` as subprocess
- Communication via stdio JSON-RPC
- Fall back to deterministic mode if spawn fails or no Python found

**WorkerSupervisor** (included in `WorkersBridge`):

```typescript
class WorkerSupervisor {
  private attempts: number = 0;
  private readonly maxRestarts: number = 3;

  // Called when a tool call times out or the process exits unexpectedly
  restartWorker(): Promise<void> {
    if (this.attempts >= this.maxRestarts) {
      throw new Error("Worker crashed too many times — falling back to deterministic mode");
    }
    this.attempts++;
    this.killChild();                // SIGTERM → 3s grace → SIGKILL
    this.spawnChild();               // Re-spawn python mcp_server.py
    return this.waitForReady();      // Wait for health check OK
  }

  // Health check: sends a ping JSON-RPC request, expects pong within 5s
  isHealthy(): Promise<boolean> { ... }
}
```

The supervisor tracks restart attempts. After 3 consecutive failures, the bridge falls back to deterministic mode (no LLM, no MCP tools). This prevents infinite crash loops while keeping long assessments alive across transient worker failures.

**MCP tool registry drift detection:**

On startup and after every worker restart, `WorkersBridge` calls `getTools()` on the MCP server and compares the result against the local `tool-definitions.yaml`:

```typescript
interface DriftReport {
  missing_from_registry: string[];   // Tools MCP exposes but registry doesn't know
  missing_from_mcp: string[];        // Tools registry expects but MCP doesn't expose
  capability_gaps: string[];         // Tools whose capabilities changed
}

// During /doctor and /assess startup
const drift = await detectDrift();
if (drift.missing_from_registry.length > 0) {
  logger.warn(`MCP exposes tools not in registry: ${drift.missing_from_registry}`);
  // Auto-add unknown tools with inferred capabilities (best-effort)
}
if (drift.missing_from_mcp.length > 0) {
  logger.warn(`Registry expects tools MCP no longer provides: ${drift.missing_from_mcp}`);
  // Planner skips phases that depend solely on missing tools
}
```

This prevents silent planner failures when the Python worker adds or removes tools without updating the capability registry.

**LLM availability signal flow:**

The planner never detects provider failures directly. Detection is layered and the bridge normalizes raw errors into typed signals the planner can act on.

```typescript
// types.ts — typed error for LLM unavailability
class LLMUnavailableError extends Error {
  constructor(
    public status: "DEGRADED" | "UNAVAILABLE",
    public retryAfter?: number,
  ) {
    super(`LLM ${status}`);
  }
}
```

**Detection layers:**

| Layer | Role |
|-------|------|
| **Provider** | Detects raw failures (HTTP 429, timeout, auth error, upstream 5xx). Normalizes to `{ status, type, retry_after }`. |
| **Bridge** | Holds circuit-breaker state. Wraps every LLM-provisioned tool call with retry/backoff. On persistent failure, emits `LLMUnavailableError` to the caller. Never leaks raw provider errors to the planner. |
| **Planner** | Catches `LLMUnavailableError` at phase boundaries. Decides: retry phase, skip to deterministic fallback, or enter sticky degraded mode. Never interprets raw provider errors. |

**Signal contract:**

```typescript
// Bridge exposes a read-only status method for health checks and recovery probes
interface WorkersBridge {
  // Primary call — may throw LLMUnavailableError
  callTool(name: string, args: unknown): Promise<ToolResult>;

  // Read-only status for health checks and recovery probes
  llmStatus(): "AVAILABLE" | "DEGRADED" | "UNAVAILABLE";

  // Events for observability — emitted on every state transition
  on(event: "llm-status-changed", handler: (status: string) => void): void;
}
```

**Signal flow:**

```text
Provider returns 429
  → Bridge catches, applies backoff
  → Retry fails again → Bridge checks circuit breaker
  → Circuit open → Bridge throws LLMUnavailableError("DEGRADED", retryAfter: 120)
  → Planner catches at phase boundary
  → Planner consults error recovery policy:
      - PHASE_ERROR_POLICY[phase] === "retry_once_then_skip" → retry once
      - If retry also fails → skip phase, continue deterministically
      - If 3 failures in 10 minutes → sticky DEGRADED mode
  → After cooldown window → bridge.llmStatus() === "AVAILABLE"
  → Planner resumes LLM for next new phase
```

Every `AVAILABLE → DEGRADED → UNAVAILABLE → AVAILABLE` transition is recorded in runtime events for observability and debugging. Phase boundaries are the primary decision points; mid-phase failures surface as typed errors that trigger fallback logic.

### 5.3 Browser/Observe & React (`src/argus/browser/`)

**Purpose:** Dynamically interact with web apps, observe behavior, verify findings.

**Generic VerificationScenario interface** (defined in `types.ts`):

```typescript
interface VerificationScenario {
  name: string;
  description: string;

  // Lifecycle — each phase returns VerifierResult
  setup(): Promise<void>;                       // Login, auth setup, precondition checks
  execute(): Promise<void>;                     // Perform the test (inject, navigate, etc.)
  verify(): Promise<VerifierResult>;            // Check result, capture evidence
  collectEvidence(): Promise<EvidencePackage>;  // Gather screenshots, HAR, dumps
}

interface VerifierResult {
  passed: boolean;
  confidence: Confidence;
  evidence: EvidencePackage[];
  summary: string;
}
```

**Files:**

| File | Responsibility |
|------|---------------|
| `types.ts` | `VerificationScenario`, `VerifierResult`, `Observation`, `DiffResult` types |
| `engine.ts` | `PlaywrightEngine` — wraps Playwright, captures screenshots and HAR |
| `observer.ts` | `ObserveLoop.observe(url)` → `Observation`, `compareObservations(a, b)` → `diff` |
| `verifiers/bola.ts` | `BOLAVerifier implements VerificationScenario` |
| `verifiers/xss.ts` | `StoredXSSVerifier implements VerificationScenario` |
| `verifiers/priv-esc.ts` | `PrivilegeEscalationVerifier implements VerificationScenario` |
| `verifiers/runner.ts` | `VerificationRunner.run(scenario)` — generic lifecycle executor |

**BOLA Workflow:**
```
BOLAVerifier
  .setup()    → Login as User A and User B sessions
  .execute()  → Navigate to /resource/ID_A as user A, then as user B
  .verify()   → Compare observations → data_exposed?
  .collectEvidence() → Screenshots from both sessions → EvidencePackage
```

**Stored XSS Workflow:**
```
StoredXSSVerifier
  .setup()    → Navigate to injectUrl
  .execute()  → Inject payload → submit
  .verify()   → Navigate to victimViewUrl → observe DOM → payload_executed?
  .collectEvidence() → Screenshot, DOM dump → EvidencePackage
```

**Privilege Escalation Workflow:**
```
PrivilegeEscalationVerifier
  .setup()    → Login as low-priv user
  .execute()  → Navigate to high-priv endpoint
  .verify()   → Observe response (200 vs 403) → access_granted?
  .collectEvidence() → Screenshot, response dump → EvidencePackage
```

Future verifiers (session replay, MFA handling, CSRF, business logic) implement the same `VerificationScenario` interface, making the browser module extensible without modifying the runner.

### 5.4 Evidence Engine (`src/argus/evidence/`)

**Purpose:** Capture evidence for every confirmed finding. Automatic during verification.

**Files:**

| File | Responsibility |
|------|---------------|
| `types.ts` | `ArtifactType`, `Artifact`, `EvidencePackage`, `EvidenceManifest`, `ArtifactEntry` types |
| `collector.ts` | `EvidenceCollector.saveRequest()`, `saveResponse()`, `captureScreenshot()` — respects `capture_threshold` and `capture_har`/`capture_video` config |
| `store.ts` | `ArtifactStore.createPackage()`, `getPackage()`, `listPackages()` — generates `EvidenceManifest` with `package_hash` on write, verifies integrity on read |
| `integrity.ts` | `verifyPackage(packageId)` → `IntegrityReport` — offline verification of evidence packages |

**Storage layout:** Metadata lives in SQLite (`argus.db`). Artifacts live on the filesystem under the engagement directory. The evidence module writes binary blobs to `~/.argus/engagements/ENG-{id}/artifacts/` and indexes metadata in SQLite.
```
~/.argus/
├── argus.db                      # SQLite (WAL mode): engagements, findings, evidence_packages, artifacts, workflow_snapshots
└── engagements/
    ├── ENG-001/
    │   └── artifacts/
    │       ├── find-001-bola/
    │       │   ├── manifest.json
    │       │   ├── screenshots/user-a-view.png
    │       │   ├── screenshots/user-b-replay.png
    │       │   ├── requests/request.txt
    │       │   └── responses/response.txt
    │       └── find-002-xss/
    │           └── ...
    └── ENG-002/
```

**SQLite schema** (`argus.db` — managed via Drizzle ORM, matching OpenCode's pattern):

```sql
CREATE TABLE engagements (
    id TEXT PRIMARY KEY,          -- ENG-{uuid}
    target TEXT NOT NULL,
    workflow TEXT NOT NULL,
    workflow_version INTEGER DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'running',
    schema_version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE findings (
    id TEXT PRIMARY KEY,          -- find-{uuid}
    engagement_id TEXT NOT NULL,
    title TEXT NOT NULL,
    severity INTEGER NOT NULL,
    confidence INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | CONFIRMED | REJECTED | FINALIZED
    description TEXT,
    cve TEXT,
    cwe TEXT,
    owasp TEXT,
    remediation TEXT,
    tool TEXT,
    phase TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,      -- Updated on confidence promotions, status changes, evidence attachment
    finalized_at TEXT,             -- Set when status becomes FINALIZED (assessment end or human action)
    FOREIGN KEY (engagement_id) REFERENCES engagements(id)
);

CREATE TABLE evidence_packages (
    id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    package_hash TEXT NOT NULL,   -- SHA256 of manifest + artifact hashes
    created_at TEXT NOT NULL,
    FOREIGN KEY (finding_id) REFERENCES findings(id)
);

CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    path TEXT NOT NULL,            -- Relative to engagement/artifacts/
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    type TEXT NOT NULL,            -- screenshot | request | response | har | log
    FOREIGN KEY (package_id) REFERENCES evidence_packages(id)
);

CREATE TABLE workflow_snapshots (
    id TEXT PRIMARY KEY,
    engagement_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,   -- e.g., "full_assessment"
    workflow_version INTEGER NOT NULL,
    workflow_yaml TEXT NOT NULL,   -- Exact YAML at time of execution — enables replay years later
    created_at TEXT NOT NULL,
    FOREIGN KEY (engagement_id) REFERENCES engagements(id)
);

-- Indexes for query performance
CREATE INDEX idx_findings_engagement ON findings(engagement_id);
CREATE INDEX idx_findings_status ON findings(status);
CREATE INDEX idx_findings_severity ON findings(severity);
CREATE INDEX idx_evidence_packages_finding ON evidence_packages(finding_id);
CREATE INDEX idx_artifacts_package ON artifacts(package_id);
CREATE INDEX idx_workflow_snapshots_engagement ON workflow_snapshots(engagement_id);

PRAGMA journal_mode=WAL;         -- Concurrent readers, crash recovery
PRAGMA foreign_keys=ON;          -- Enforce referential integrity
```

**Migration strategy:** Schema changes are managed via Drizzle Kit. Each change is a migration file in `cli/src/argus/engagement/migrations/`. On startup, `EngagementStore` runs `migrate()` which applies any unapplied migrations in order. The `schema_version` column on `engagements` enables per-engagement migration — old engagements are migrated on first access (lazy), not on startup. Backward-incompatible changes create a new `schema_version`; old rows are migrated via a `store.ts` migration function.

**Phase lifecycle** (alongside assessment and finding states):

```text
Phase lifecycle:    PENDING → RUNNING → COMPLETED | FAILED | SKIPPED
Assessment lifecycle:  CREATED → RUNNING → PAUSED → RUNNING → COMPLETED | FAILED
Finding lifecycle:     PENDING → [confidence promotions] → CONFIRMED | REJECTED | FINALIZED
LLM circuit-breaker:   AVAILABLE → DEGRADED → UNAVAILABLE → [cooldown] → AVAILABLE
```

All four state machines are independent. An assessment can be `RUNNING` while individual phases are `FAILED` (error recovery skips and continues). A finding can be `FINALIZED` while the assessment is still `RUNNING` (human `/confirm`). The LLM circuit-breaker cycles independently of the assessment — it can recover mid-assessment.

**Failure handling matrix:**

| Failure | Detection | Recovery | User-visible |
|---------|-----------|----------|--------------|
| **Tool missing from PATH** | Toolchain check in `/doctor` | Planner skips phase capability, continues with available tools | WARN in assessment output, logged |
| **MCP worker crash** | `WorkerSupervisor.isHealthy()` ping fails | Auto-restart up to 3 times, then deterministic fallback | Phase marked `PARTIAL`, assessment continues |
| **SQLite locked** | `SQLITE_BUSY` from Drizzle | Retry with exponential backoff (up to 3s), then fail phase | Phase marked `FAILED` with DB error detail |
| **LLM unavailable** | `LLMUnavailableError` thrown by bridge | Per-phase deterministic fallback; sticky DEGRADED after 3 failures in 10min; recovery probe re-enables LLM for new phases | Phase mode tag switches from `llm` to `deterministic` |
| **Browser launch failure** | Playwright throws on `browser.launch()` | Skip browser verification phases, continue with tool-only findings | Verification scenarios marked `SKIPPED_BROWSER_UNAVAILABLE` |
| **Credential role missing** | `CredentialStore.get("victim")` returns null | Skip dependent verification scenario, record `SKIPPED_MISSING_ROLE` | Finding entry with skip reason, assessment continues |

Every failure case maps to one of: retry, skip phase, fall back, or degrade — never abort the entire assessment.

**Evidence chain integrity:** Each evidence package includes a `manifest.json` with SHA256 hashes of all contained artifacts, plus a `package_hash` stored in SQLite covering manifest + artifact hashes. This provides tamper detection for the entire package independent of the database.

```typescript
interface EvidenceManifest {
  package_id: string;             // e.g., "find-001-bola"
  engagement_id: string;          // ENG-{uuid}
  created_at: string;             // ISO 8601
  artifacts: ArtifactEntry[];     // File paths + SHA256 hashes
  package_hash: string;           // SHA256(JSON(manifest) + Σ(artifact_hashes))
}

interface ArtifactEntry {
  path: string;                   // Relative path within package
  hash: string;                   // SHA256 of file content
  type: ArtifactType;             // screenshot | request | response | har | log
  size_bytes: number;
}
```

The `EvidenceCollector.createPackage()` generates the manifest after all artifacts are collected. Integrity can be verified offline with `argus verify-package <package-id>`.

**Storage layout with manifest:**

```
~/.argus/
├── argus.db                        # SQLite: engagements, findings, evidence_packages, artifacts
└── engagements/
    ├── ENG-001/
    │   └── artifacts/
    │       ├── find-001-bola/
    │       │   ├── manifest.json           # EvidenceManifest with package_hash
    │       │   ├── screenshots/user-a-view.png
    │       │   ├── screenshots/user-b-replay.png
    │       │   ├── requests/request.txt
    │       │   └── responses/response.txt
    │       └── find-002-xss/
    │           └── ...
    └── ENG-002/
```

**Storage limits and retention:**

```yaml
# ~/.argus/config.yaml
evidence:
  retention_days: 30              # Auto-prune artifacts older than N days
  max_engagement_size_mb: 500     # Hard limit per engagement; warn at 80%
  prune_on_completion: true       # Run /evidence prune after every /assess
  capture_har: false              # HAR capture disabled by default (can be GBs)
  capture_video: false            # Video capture disabled by default
  capture_threshold: HIGH         # Minimum confidence to capture full artifacts (HAR/video)
```

These defaults are enforced by `EvidenceCollector` before writes. For findings below `capture_threshold`, only lightweight evidence (screenshots, response snippets) is collected. Full HAR and video are captured only for findings at HIGH or above. When an engagement exceeds `max_engagement_size_mb`, oldest screenshots are compressed (PNG→JPEG 85%) before newer artifacts are rejected. The `/evidence prune --keep-last=N` command from Task 2.2 respects `retention_days` as the default N.

### 5.5 Reporting (`src/argus/reporting/`)

**Purpose:** Generate professional reports with embedded evidence.

**NormalizedFinding schema** (the unified finding format used by all report generators):

```typescript
enum Severity {
  INFO = 0,
  LOW = 1,
  MEDIUM = 2,
  HIGH = 3,
  CRITICAL = 4,
}

interface NormalizedFinding {
  id: string;                    // find-{uuid}
  title: string;
  severity: Severity;
  confidence: Confidence;
  status: "PENDING" | "CONFIRMED" | "REJECTED" | "FINALIZED";
  description: string;
  evidence: EvidencePackage[];
  cve?: string;                  // CVE identifier if applicable
  cwe?: string;                  // CWE classification
  owasp?: string;                // OWASP Top 10 category
  remediation?: string;          // Recommended fix
  tool: string;                  // Source tool (nuclei, browser-verifier, etc.)
  phase: string;                 // Which phase discovered this
  created_at: string;            // ISO 8601 — when tool first reported
  updated_at: string;            // ISO 8601 — last confidence promotion or status change
  finalized_at?: string;         // ISO 8601 — set when assessment completes or human confirms/rejects
}
```

All findings from tools (Nuclei, Nikto, custom scanners, browser verifiers) are converted into `NormalizedFinding` before entering the evidence store or report pipeline. This decouples report generation from tool-specific output formats.

**Finding lifecycle:**

```text
Tool reports finding
  → NormalizedFinding created (status: PENDING, confidence: LOW)
  → ConfidenceEngine.promote() updates same finding record (confidence: MEDIUM → HIGH)
  → Browser verification passes (confidence: VERIFIED)
  → Human runs /confirm (status: CONFIRMED, finalized_at: now)
  OR assessment completes (status: FINALIZED, finalized_at: now)
```

Findings are **mutable during the assessment**. Confidence promotions update the same record — they never create new findings. A finding is finalized only when the assessment completes or a human explicitly confirms/rejects it. The `status` field disambiguates open vs. resolved findings in all output formats.

**Report generation model:**

Reports are **snapshots**, not incremental logs. The `ReportGenerator` always re-queries the SQLite evidence store on every invocation:

```text
/report markdown
  → SELECT * FROM findings WHERE engagement_id = 'ENG-001'
  → SELECT * FROM evidence_packages JOIN artifacts WHERE finding_id IN (...)
  → ReportGenerator.generateMarkdown(findings, artifacts)
```

This means `/report` can be called multiple times, with each invocation reflecting the latest evidence, confidence promotions, confirmations, and late-arriving artifacts. Reports are deterministic — identical database state always produces identical output. Audit log (timeline of changes) is stored separately and is not part of the report artifact.

**Files:**

| File | Responsibility |
|------|---------------|
| `normalizer.ts` | `normalizeFinding(raw: unknown)` → `NormalizedFinding` — converts tool-specific output to unified format |
| `generator.ts` | `ReportGenerator.generateMarkdown()`, `generateHTML()`, `generateSARIF()`, `generateJSON()` — re-queries SQLite on each call |
| `templates/` | Jinja2-style HTML template (future), Markdown template |

### 5.6 CLI Commands

| Command | Function | Builder |
|---------|----------|---------|
| `/assess <target>` | Full autonomous assessment | Planner → MCP bridge → Browser verifier → Evidence → Report |
| `/doctor` | Comprehensive health check | Checks: runtime, MCP (live subprocess + JSON-RPC ping), Playwright (headless launch + navigation), providers (LLM endpoint), toolchain (capability binaries on PATH), database (SQLite + WAL), local-only — never contacts assessment target |
| `/verify <finding-id>` | Re-run browser verification | Browser verifier only, reuses existing evidence package |
| `/report [format]` | Generate/regenerate report | Report generator, reads from ArtifactStore |
| `/evidence [list/show]` | Browse captured evidence | ArtifactStore queries |
| `/resume <engagement-id>` | Resume a saved assessment | Engagement store → planner → continue from last incomplete phase |
| `/config` | Show effective config | Prints resolved config with source annotations for each value |

Existing OpenCode commands (`/scan`, `/recon`, `/auth`, `/api`) map to direct MCP tool calls, bypassing the planner.

**`/doctor` check categories:**

| Category | Checks | Invasive? |
|----------|--------|-----------|
| **Runtime** | Node.js version, OpenCode fork integrity, config file loads, `~/.argus/` directory writable | No |
| **MCP** | Spawns actual MCP subprocess, sends JSON-RPC `ping`, verifies response serialization and worker version compatibility, confirms `WorkerSupervisor` health check passes | Yes (subprocess, but read-only) |
| **Browser** | Launches headless Playwright, creates context, navigates to `about:blank`, captures temp screenshot, cleanly shuts down. Skips if `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` is set | Yes (browser, but read-only, no target) |
| **Providers** | Tests configured LLM provider endpoint with a minimal prompt (`"ping"`). Only runs with `--online` flag. Warns on failure, does not block. | Yes (network, but configurable) |
| **Toolchain** | For every capability in the registry, verifies the mapped binary exists on PATH. Reports missing tools as WARN, not FAIL (tools can be installed mid-assessment). | No |
| **Database** | Opens `~/.argus/argus.db`, runs `PRAGMA integrity_check`, verifies WAL mode is enabled, confirms migrations are current. | No |

**Output:** All checks return structured `PASS | WARN | FAIL` results. Supports `--json` flag for CI integration. Each check has a maximum timeout (default 30s) — `/doctor` never hangs indefinitely. The assessment target is never contacted; all checks are either local or limited to LLM provider connectivity (with `--online`).

### 5.7 Workflow Registry (`src/argus/workflows/`)

**Purpose:** Decouple workflow logic from planner code. New workflows can be added without TypeScript changes.

**Files:**

| File | Responsibility |
|------|---------------|
| `registry.ts` | `WorkflowRegistry.loadAll()`, `getWorkflow(name)`, `listWorkflows()` — loads YAML from `workflows/` dir |
| `loader.ts` | `loadWorkflowYaml(path)` → `WorkflowDefinition` with validation |
| `types.ts` | `WorkflowDefinition`, `Phase`, `ToolRequirement`, `ApprovalGate` types |
| `api_assessment.yaml` | API assessment workflow definition |
| `bola.yaml` | BOLA verification workflow |
| `xss.yaml` | Stored XSS verification workflow |
| `privilege_escalation.yaml` | Privilege escalation verification workflow |
| `full_assessment.yaml` | Full web app assessment workflow |

**Workflow YAML format:**

```yaml
name: full_assessment
label: Full Web Assessment
version: 1           # Increment on breaking changes; stored in EngagementState for resume compat
phases:
  - name: recon
    required_capabilities:
      - web_recon
      - port_scanning
      - technology_detection
    execution: parallel          # Tools satisfying these caps run concurrently
    error_recovery: retry_once_then_skip
  - name: auth_detection
    required_capabilities:
      - auth_detection
      - credential_analysis
    execution: sequential
    error_recovery: skip_and_continue
  - name: api_discovery
    required_capabilities:
      - content_discovery
      - api_probing
    execution: parallel
    approval_gate: destructive_tools
    error_recovery: skip_and_continue
  - name: vuln_scan
    required_capabilities:
      - vulnerability_scanning
      - template_scanning
    execution: parallel          # Multiple vuln scanners run simultaneously
    error_recovery: retry_once_then_skip
  - name: verification
    required_capabilities:
      - browser_verification
    execution: sequential
    error_recovery: skip_and_continue
  - name: reporting
    required_capabilities:
      - report_generation
    execution: sequential
    error_recovery: fail_fast
approval_required:
  destructive_tools: true
  auth_testing: false
  privilege_escalation: true
```

Phases define **what** capabilities are needed and **how** to execute (parallel vs sequential). The planner resolves capabilities to concrete tools via `ToolRegistry.getToolsByCapability()` at plan time. Deterministic fallback selects the YAML with the closest name match to detected target type.

### 5.8 Tool Capability Registry

**Purpose:** Enable the planner to reason about tool capabilities rather than hardcoded tool names.

**Files:**

| File | Responsibility |
|------|---------------|
| `src/argus/workflows/tool-registry.ts` | `ToolRegistry.load()`, `getToolsByCapability(cap)`, `getCapabilities(toolName)` |
| `src/argus/workflows/tool-definitions.yaml` | Tool capability metadata |

**Tool definition YAML format:**

```yaml
name: nuclei
label: Nuclei Vulnerability Scanner
capabilities:
  - vuln_scan
  - template_scan
requires_auth: false
destructive: false
supports_api: true
supports_web: true
timeout_seconds: 300
scoring:                       # Used by ToolRegistry to rank candidates
  confidence_score: 90         # How reliable are this tool's findings (0-100)
  speed_score: 85              # How fast does this tool run (0-100)
  stability_score: 95          # How often does this tool complete without error (0-100)
---
name: sqlmap
label: SQL Injection Automation
capabilities:
  - sqli_detection
  - database_exfiltration
requires_auth: false
destructive: true
supports_api: true
supports_web: true
timeout_seconds: 600
approval_required: true
scoring:
  confidence_score: 95
  speed_score: 40
  stability_score: 80
---
name: httpx
label: HTTP Probe
capabilities:
  - http_probe
  - technology_detection
requires_auth: false
destructive: false
supports_api: true
supports_web: true
timeout_seconds: 120
scoring:
  confidence_score: 85
  speed_score: 98
  stability_score: 99
```

**Planner integration:** `selectTools(phase, target)` queries `ToolRegistry.getToolsByCapability(phase.required_capabilities)`. When multiple tools satisfy the same capability, the registry ranks candidates by weighted score:

```typescript
interface ToolRankingWeights {
  confidence: number;   // default 0.5
  speed: number;        // default 0.3
  stability: number;    // default 0.2
}

// ToolRegistry.selectBest(capabilities, weights) → ToolDefinition[]
// Sorts candidates by Σ(score_i * weight_i), returns top 1-3 tools per capability
```

This prevents arbitrary tool selection. For a quick scan, speed_weight is increased. For a thorough assessment, confidence_weight dominates.

### 5.9 Engagement State Store (`src/argus/engagement/`)

**Purpose:** Persist assessment progress so long-running scans can survive interruptions and be resumed.

**Files:**

| File | Responsibility |
|------|---------------|
| `schema.ts` | Drizzle ORM schema definitions for `engagements`, `findings`, `evidence_packages`, `artifacts` tables |
| `store.ts` | `EngagementStore.create()`, `save()`, `load(id)`, `list()`, `delete()` — backed by SQLite via Drizzle |
| `types.ts` | `EngagementState`, `PhaseStatus`, `Finding`, `EngagementMetadata` types |
| `recovery.ts` | `resumeFromLastComplete(engagement)` → returns next incomplete phase — reads from SQLite, validates `workflow_version` match |

**Confidence model** (defined in `types.ts`):

```typescript
enum Confidence {
  INFORMATIONAL = 0,  // Raw observation, no verification
  LOW = 1,            // Tool-reported, minimal evidence
  MEDIUM = 2,         // Tool-reported with corroborating evidence
  HIGH = 3,           // Multiple tools agree, strong evidence
  VERIFIED = 4,       // Browser or manual verification passed
  CONFIRMED = 5,      // Fully confirmed with evidence package
}

interface Finding {
  id: string;
  title: string;
  description: string;
  confidence: Confidence;
  cve?: string;
  cwe?: string;
  evidence: EvidencePackage[];
  phase: string;
  tool: string;
}
```

**ConfidenceEngine** (defined in `confidence.ts`):

```typescript
class ConfidenceEngine {
  // Deterministic promotion rules — no subjectivity
  static promote(finding: Finding, context: PromotionContext): Confidence {
    // Tool-reported only
    if (context.toolCount === 1 && !context.corroborated)
      return Confidence.LOW;

    // Multiple tools agree on same finding
    if (context.toolCount >= 2 && context.corroborated)
      return Confidence.HIGH;

    // Single tool with strong signal (e.g., SQLi evidence in response)
    if (context.toolCount === 1 && context.strongSignal)
      return Confidence.MEDIUM;

    // Browser verification passed
    if (context.browserVerified)
      return Confidence.VERIFIED;

    // Human review / manual confirmation
    if (context.humanApproved)
      return Confidence.CONFIRMED;

    return Confidence.INFORMATIONAL;
  }
}

interface PromotionContext {
  toolCount: number;          // How many independent tools flagged this
  corroborated: boolean;      // Do tools agree on the same root cause?
  strongSignal: boolean;      // Single tool with definitive evidence
  browserVerified: boolean;   // Playwright verification passed
  humanApproved: boolean;     // Manual confirmation
}
```

**Promotion flow:**

```text
Tool runs
  → LOW (single tool, no cross-ref)
  → If second tool agrees → MEDIUM
  → If 2+ tools agree with strong signal → HIGH
  → Browser verification pass → VERIFIED
  → Human `/confirm` command → CONFIRMED
```

The `ConfidenceEngine` is called by the planner after each phase. Findings are evaluated against `PromotionContext` which is built from engagement state, evidence store queries, and verifier results.

**Engagement state format** (mapped to SQLite via Drizzle ORM — the `EngagementState` type is reconstructed from DB rows at runtime):

```typescript
// Runtime representation — hydrated from SQLite on load
interface EngagementState {
  id: string;
  target: string;
  workflow: string;
  workflow_version: number;
  status: "running" | "paused" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  schema_version: number;

  // Reconstructed from SQLite queries — not stored as JSON
  completedPhases(): Promise<string[]>;
  currentPhase(): Promise<string | null>;
  findings(): Promise<Finding[]>;
}
```

State and findings are **not** stored as JSON files. They are rows in SQLite tables. The `engagements` table stores the core state; the `findings` table stores findings with foreign key to engagement; `phase_results` is stored as a JSON column on the engagement row (a single small blob, not the full artifact list).

**Storage layout:**

```
~/.argus/
├── argus.db                      # SQLite (WAL mode): all metadata, state, findings
└── engagements/
    ├── ENG-001/
    │   └── artifacts/            # Binary blobs only
    │       ├── find-001-bola/
    │       │   ├── manifest.json
    │       │   ├── screenshots/
    │       │   └── requests/
    │       └── find-002-xss/
    │           └── ...
    └── ENG-002/
```

No `state.json`, no `findings.json`, no `index.json`. The sole source of truth for metadata is `argus.db`. Artifacts on disk are self-validating via `manifest.json` but indexed in SQLite for query performance.

**Workflow snapshots:** When an assessment starts, the exact workflow YAML is stored in the `workflow_snapshots` table. This ensures that `resume` and historical report generation always use the same workflow definition that produced the original findings — even if the YAML file has been updated.

**Resume workflow:**

```text
argus resume ENG-001
  → EngagmentStore.load("ENG-001")
     → SELECT * FROM engagements WHERE id = 'ENG-001'
     → SELECT * FROM findings WHERE engagement_id = 'ENG-001'
     → SELECT * FROM workflow_snapshots WHERE engagement_id = 'ENG-001'
     → Verify schema_version matches runtime
     → Compare workflow_version; if YAML changed, use snapshot
  → Determine last incomplete phase
  → Recreate planner context from saved findings + snapshot
  → Continue execution from that phase
  → INSERT/UPDATE rows in SQLite on each phase completion
```

### 5.10 Human Approval Gates

**Purpose:** Prevent autonomous execution from running destructive or sensitive operations without user consent.

**Files:**

| File | Responsibility |
|------|---------------|
| `src/argus/commands/approval.ts` | `ApprovalGate.request(operation, context)` → prompts user; `isApproved(operation, flags)` → boolean |
| `src/argus/workflows/approval-policies.yaml` | Per-workflow approval policies |

**Policy YAML format:**

```yaml
approval_policies:
  destructive_tools:
    prompt: "Tool {tool} is potentially destructive. Continue?"
    interactive_behavior: prompt    # prompt | skip | force
    auto_behavior: skip             # prompt | skip | force
  auth_testing:
    prompt: "This test will attempt authenticated operations on {target}. Continue?"
    interactive_behavior: prompt
    auto_behavior: prompt           # Always prompt even in --auto for auth testing
  privilege_escalation:
    prompt: "Attempting privilege escalation on {target}. This may trigger alerts. Continue?"
    interactive_behavior: prompt
    auto_behavior: skip
```

**Approval flow:**

```text
Planner selects workflow
  → Check approval_required in workflow definition
  → ApprovalGate.request(operation, {tool, target, reason})
  → Interactive: prompt user (Y/n)
  → --auto mode: check auto_behavior in policy
  → Approved: continue execution
  → Denied: skip phase, mark as skipped in engagement state, continue to next phase
```

This is wired into `runPhase()` as a pre-execution gate, sharing the `ErrorRecovery` infrastructure from Task 0.4.

---

## 6. Architecture Review (V5 TypeScript Fork)

### 6.1 Summary Assessment

**Overall: Conditionally approved — 4 blocking issues must be resolved before implementation begins.**

| Severity | Count | Area |
|----------|-------|------|
| 🔴 Blocking | 2 | MCP server readiness, cross-platform process lifecycle |
| 🟡 Major | 3 | Credential management, error recovery, Playwright installation |
| 🔵 Minor | 3 | Evidence cleanup, JSON index corruption, Python version discovery |

### 6.2 Blocking Issues

#### Issue 1: MCP Server is NOT a Runnable Process

**Finding:** The existing `mcp_server.py` (334 lines) defines an `MCPServer` **class** — not a standalone process. It has no `if __name__ == "__main__"` entry point, no stdin/stdout JSON-RPC loop, and no transport layer.

```python
# Current state — class only, no runtime entry point
class MCPServer:
    def call_tool(self, name, arguments, timeout): ...
    def get_tools(self): ...
```

**Fix required:** Create `argus-workers/mcp_transport.py` — a thin stdio transport layer on top of the existing `MCPServer` class. Don't modify `mcp_server.py` itself (preserve backward compat).

#### Issue 2: Child Process Lifecycle Not Addressed

**Finding:** The TypeScript CLI spawns `python mcp_server.py` as a subprocess. If the user presses Ctrl+C during a 5-minute scan:
1. Python process continues running (orphan)
2. Stdio pipes become half-closed
3. Next assessment spawns a second Python process (zombie accumulation)

**Fix required:** `WorkersBridge` must forward SIGTERM/SIGINT to child, with 3s graceful shutdown then SIGKILL.

### 6.3 Major Issues

#### Issue 3: Error Recovery Is Underspecified

**Fix:** Add an error recovery table to the spec for `runPhase()`:

```typescript
type ErrorRecovery = "fail_fast" | "skip_and_continue" | "retry_once_then_skip";

const PHASE_ERROR_POLICY: Record<string, ErrorRecovery> = {
  "recon": "retry_once_then_skip",
  "vuln_scan": "retry_once_then_skip",
  "verification": "skip_and_continue",
  "reporting": "fail_fast",
};
```

#### Issue 4: Credential Management Not Addressed

**Fix:** CLI `--creds` flag pointing to a JSON file with role-keyed credentials:

```json
{
  "roles": {
    "admin": {
      "username": "admin@target.com",
      "password": "admin123"
    },
    "user": {
      "username": "user@target.com",
      "password": "user123"
    },
    "attacker": {
      "username": "hacker@target.com",
      "password": "hack123"
    },
    "victim": {
      "username": "user@target.com",
      "password": "user123"
    }
  },
  "target": {
    "login_url": "https://target.com/login",
    "login_username_selector": "#username",
    "login_password_selector": "#password",
    "login_submit_selector": "#login-btn"
  }
}
```

Roles are semantic identifiers rather than positional array indices. Workflows request credentials by role:

```typescript
const victimCreds = credentials.get("victim");
const attackerCreds = credentials.get("attacker");
```

This makes BOLA, XSS, and privilege escalation verifiers self-documenting — each reads the role it needs by name, not by array position.

**Credential lifecycle:**

| Concern | Design |
|---------|--------|
| **Load timing** | Once at `/assess` start. Schema validated immediately — fail fast on malformed files. |
| **Ownership** | Dedicated `CredentialStore` passed into `PlannerContext` as a reference/accessor. No global singleton. |
| **Missing role** | Do **not** abort the assessment. Mark the verification scenario as `SKIPPED_MISSING_ROLE`, record the skip in findings, continue the engagement. |
| **Python worker access** | Credentials are **not** automatically forwarded to the MCP worker. Least-privilege forwarding only: specific role, specific task, ephemeral transmission. Planner must explicitly approve before any credential crosses the MCP boundary. |
| **Memory safety** | Zeroize credentials from memory on assessment completion. Track credential usage in audit log: `{ role, phase, timestamp }`. |
| **Absent `--creds`** | Browser verification scenarios are skipped entirely. All other phases proceed normally. |

#### Issue 5: Playwright Browser Installation

**Fix:** Add to `package.json` postinstall script and `/doctor` check.

### 6.4 Minor Issues

| # | Issue | Fix |
|---|-------|-----|
| 6 | Evidence store has no cleanup policy | Add `/evidence prune --keep-last=N` and auto-clean artifacts older than 30 days |
| 7 | JSON index not safe for concurrent access | Add file locking (lockfile or exclusive write with rename) |
| 8 | Python discovery is not cross-platform | Support `ARGUS_PYTHON` env var, `/doctor` validates Python availability |

---

## 7. Backend Codebase Review (argus-workers Python Engine)

### 7.1 Overall Assessment

**Score: 7.5/10**

The Python backend has a well-thought-out architecture with strong fundamentals — state machine with FOR UPDATE locking, circuit breaker, structured logging, and Celery routing. Five categories of issues were identified, from connection management to observability.

### 7.2 P0 — Critical Gaps

#### Gap B-01: Database Connection Leak in State Machine

**File:** `argus-workers/state_machine.py`

**Problem:** `_get_connection()` supports three code paths: external connection, raw connection string (`connect()`), and pool (`get_db()`). When `_db_conn_string` is provided, `_release_connection()` calls `conn.close()` instead of returning the connection to the pool. This leaks pool-managed connections. Additionally, `_resolve_state_if_needed()` reads state without a FOR UPDATE lock, then `transition()` re-reads under lock — a TOCTOU window.

**Fix:**
- Remove the raw connection string path entirely — always use the pool
- Add deprecation warning when `_db_conn_string` is passed
- Consolidate to a single pool-based code path

**Task:** `B.01`

#### Gap B-02: CVE/EPSS Caching Missing

**File:** `argus-workers/intelligence_engine.py` (lines 792-893)

**Problem:** `enrich_findings_with_threat_intel()` calls NVD and EPSS APIs for every finding with no caching layer. If two findings reference the same CVE, it is fetched twice. There is no rate limiting, so under load the worker will get throttled by NVD API.

**Fix:**
- Add Redis-backed TTL cache for CVE/EPSS responses using existing `cache.py` infrastructure
- Cache key: `threat_intel:cve:{CVE_ID}` with 1-hour TTL
- Fall back to in-memory dict cache when Redis is unavailable

**Task:** `B.02`

### 7.3 P1 — High Priority Gaps

#### Gap B-03: Busy-Wait Loop in Connection Acquisition

**File:** `argus-workers/database/connection.py` (lines 160-173)

**Problem:** `ConnectionManager.get_connection()` uses `time.sleep()` in a retry loop when all pool connections are busy. This burns CPU under contention (busy-wait) and provides no backpressure signal.

**Fix:**
- Replace busy-wait with `threading.Condition.wait(timeout)`
- Signal via `Condition.notify()` when a connection is released back to pool
- Keep the existing timeout-based deadline

**Task:** `B.03`

#### Gap B-04: Retry Backoff Lacks Jitter

**Files:** `argus-workers/config/constants.py` (line 22), `argus-workers/orchestrator_pkg/scan.py`

**Problem:** `RETRY_BACKOFF_BASE = 2` with no jitter. When multiple tools fail simultaneously (e.g., network blip), all retries happen at the exact same interval, creating a thundering herd on the target or database.

**Fix:**
- Add uniform jitter: `delay * (1 + random())` so retries spread naturally
- Update `MAX_TOOL_RETRIES` usage across all retry call sites

**Task:** `B.04`

#### Gap B-05: Global Exception Swallowing in State Resolution

**File:** `argus-workers/state_machine.py` (lines 104-110)

**Problem:** `_resolve_state_if_needed()` catches all `Exception` types and defaults to `"created"`. A `psycopg2.OperationalError` (DB down) silently resets the engagement to nascent state, masking infrastructure failures.

**Fix:**
- Catch specific exceptions (`psycopg2.Error`, `DatabaseConnectionError`)
- Re-raise `DatabaseConnectionError` instead of swallowing
- Only default to `"created"` on `ValueError` (row not found)

**Task:** `B.05`

#### Gap B-06: Missing OpenTelemetry Integration

**File:** `argus-workers/tracing.py`

**Problem:** Custom `ExecutionSpan` writes execution spans to the same Postgres database being traced. This creates a cycle that can mask DB outages — if the DB is slow, tracing queries make it worse. Metrics (`connection.py:_metrics`) are in-memory dicts lost on restart.

**Fix:**
- Replace custom span recorder with OpenTelemetry exporter (console + OTLP)
- Keep `StructuredLogger` for structured logging (structlog-based)
- Add Prometheus `/metrics` endpoint (optional)

**Task:** `B.06`

### 7.4 P2 — Medium Priority Gaps

#### Gap B-07: `GIT_HOST_ALLOWLIST` Is Hardcoded

**File:** `argus-workers/config/constants.py` (lines 33-47)

**Problem:** The git SSRF allowlist is a hardcoded tuple. Organizations with self-hosted GitLab instances must patch source code to add their internal hosts.

**Fix:**
- Move to `argus_config.yaml` under `security.allowed_git_hosts`
- Support env var override (`ARGUS_ALLOWED_GIT_HOSTS`)
- Keep the current list as default

**Task:** `B.07`

#### Gap B-08: Secrets at Rest Are Unencrypted

**File:** `argus-cli/argus_cli/session/manager.py`, `argus-cli/argus_cli/config/settings.py`

**Problem:** API keys and credentials are stored in plaintext SQLite database and TOML config files on disk.

**Fix:**
- Encrypt sensitive values using a derived key from a machine-local secret
- Use `cryptography.fernet` or keyring integration

**Task:** `B.08`

### 7.5 P3 — Low Priority / Nice-to-Have

| # | Gap | Fix | Task |
|---|-----|-----|------|
| B-09 | CWE/OWASP mappings hardcoded in `parsers/normalizer.py` | Extract to external YAML/JSON config file | `B.09` |
| B-10 | No async I/O — heavy reliance on threads | Migrate hot paths (LLM, parsers) to `asyncio` with `--pool=gevent` | `B.10` |
| B-11 | Missing structured error taxonomy | Create typed error classes (`EngagementNotFoundError`, `StateRaceError`) | `B.11` |
| B-12 | Config `constants.py` has 101 lines of module-level constants | Group into dataclasses or sectioned config objects | `B.12` |

---

## 8. Consolidated Implementation Tasks

### Phase 0: Architecture Gaps (V5 TypeScript Fork — from Architecture Review)

- [ ] **Task 0.0.1:** Define canonical `Capability` enum in `src/argus/planner/capabilities.ts` — single source of truth, YAML validation against it at load time. **Done means:** enum covers all capabilities referenced in workflow YAMLs; YAML loader rejects unknown capability strings at startup.
- [ ] **Task 0.0.2:** Add workflow versioning — `version: 1` to all YAML files, `workflow_version` field to `EngagementState`. **Done means:** every workflow YAML has a version header; `EngagementState.workflow_version` is set on creation; resume validates version match and falls back to snapshot if drifted.
- [ ] **Task 0.0.3:** Add replan cycle prevention — `executedCapabilities: Set<Capability>`, `insertedPhases: Set<string>`, `MAX_REPLANS = 10` hard limit in `PlannerContext`. **Done means:** deterministic `replan-rules.ts` engine operates on enum values only; `replan()` returns `null` after 10 cycles; duplicate capabilities are never inserted.
- [ ] **Task 0.0.4:** Upgrade credential schema to role-based — `roles: { attacker, victim, admin, user }` with `credentials.get("roleName")`. **Done means:** `CredentialStore` interface defined; browser verifiers call `get("victim")` by role name; missing roles produce `SKIPPED_MISSING_ROLE` not abort; credentials zeroized on assessment completion.
- [ ] **Task 0.0.5:** Add MCP registry drift detection — `detectDrift()` compares `getTools()` results against `tool-definitions.yaml` on startup and after worker restart. **Done means:** drift report generated on every `/assess` start; unknown tools auto-added with inferred capabilities; missing tools logged and skipped; `/doctor` includes drift check.
- [ ] **Task 0.15:** Define SQLite (Drizzle ORM) schema — `engagements`, `findings`, `evidence_packages`, `artifacts`, `workflow_snapshots` tables, WAL mode, Drizzle migration framework with schema versioning strategy, workflow snapshot storage for reproducibility. Replaces all JSON index/state files.
- [ ] **Task 0.1:** Create `argus-workers/mcp_transport.py` — stdio JSON-RPC transport loop
- [ ] **Task 0.2:** Add child process lifecycle management to `WorkersBridge` — SIGTERM/SIGINT forwarding, 3s graceful shutdown then SIGKILL, orphan prevention
- [ ] **Task 0.3:** Define credential file format (`--creds`) and schema — JSON file with user array + target config
- [ ] **Task 0.4:** Define error recovery matrix per phase — `ErrorRecovery` type per phase
- [ ] **Task 0.5:** Add Playwright browser installation check to `/doctor` + `package.json` postinstall
- [ ] **Task 0.6:** Add `ARGUS_PYTHON` env var and cross-platform Python discovery logic
- [ ] **Task 0.7:** Write and extract ADR documents to `docs/adr/ADR-001.md` through `docs/adr/ADR-016.md`. Each ADR follows the template: Context → Decision → Consequences → Alternatives. Main architecture doc retains a one-line summary and link per ADR.
- [ ] **Task 0.8:** Define `Confidence` enum and `Finding` types in `src/argus/engagement/types.ts` — INFORMATIONAL through CONFIRMED
- [ ] **Task 0.9:** Create approval gates framework — `src/argus/commands/approval.ts` with policy YAML reader, interactive prompt, and `--auto` behavior
- [ ] **Task 0.10:** Create workflow registry scaffolding — `src/argus/workflows/` dir, YAML schemas, `registry.ts` stub
- [ ] **Task 0.11:** Add `WorkerSupervisor` to `src/argus/bridge/supervisor.ts` — health checks, restart logic, max 3 attempts then deterministic fallback
- [ ] **Task 0.12:** Define `PlannerContext` interface with `findings` field and `replan()` method signature — enables dynamic planning across phases
- [ ] **Task 0.13:** Define `NormalizedFinding` schema and `Severity` enum in `src/argus/reporting/types.ts`

### Phase B: Backend Codebase Remediation (Python Engine)

#### B.0 — Critical (must do before Phase 1)

- [ ] **Task B.01:** Fix connection leak in `state_machine.py` — remove raw conn string path, always use pool
- [ ] **Task B.02:** Add Redis-backed CVE/EPSS caching in `intelligence_engine.py` — 1-hour TTL, in-memory fallback

#### B.1 — High Priority

- [ ] **Task B.03:** Replace busy-wait loop in `ConnectionManager.get_connection()` with `threading.Condition`
- [ ] **Task B.04:** Add uniform jitter to retry backoff across all retry sites
- [ ] **Task B.05:** Narrow exception handling in `_resolve_state_if_needed()` — re-raise DB errors
- [ ] **Task B.06:** Replace custom `ExecutionSpan` with OpenTelemetry exporter

#### B.2 — Medium Priority

- [ ] **Task B.07:** Move `GIT_HOST_ALLOWLIST` to runtime YAML config with env var override
- [ ] **Task B.08:** Encrypt secrets at rest in SQLite session store and TOML config

#### B.3 — Low Priority

- [ ] **Task B.09:** Extract CWE/OWASP mappings from normalizer to external config
- [ ] **Task B.10:** Migrate hot-path I/O to asyncio (LLM client, parsers, threat intel)
- [ ] **Task B.11:** Create typed error class hierarchy
- [ ] **Task B.12:** Refactor `constants.py` into grouped dataclasses

### Phase 1: Foundation (V5 CLI)

- [ ] **Task 1.1:** Clone OpenCode into `cli/`, verify `argus --help` works
- [ ] **Task 1.2:** Rename package to `argus` in `package.json`, update all branding
- [ ] **Task 1.3:** Create `ARCHITECTURE_BOUNDARIES.md`
- [ ] **Task 1.4:** Set up GitHub Actions (lint → typecheck → unit tests)
- [ ] **Task 1.5:** Write `src/argus/bridge/mcp-client.ts` — subprocess MCP connection with lifecycle management from Task 0.2

### Phase 2: Core Modules (V5 CLI)

> **Recommended execution order:** Build the registry and store first (2.5, 2.6), then the planner (2.1) — so the planner is built on top of the WorkflowRegistry rather than hardcoded logic. Evidence (2.2) and reporting (2.3) follow naturally, with browser (2.4) last since it depends on all other modules.

- [ ] **Task 2.5:** Implement `src/argus/workflows/` — registry, loader, types, YAML definitions for all 5 built-in workflows (capability-based, with `execution: parallel|sequential`), tool capability registry with scoring-based ranking (`ToolRegistry.selectBest()`), tests
- [ ] **Task 2.6:** Implement `src/argus/engagement/` — Drizzle ORM schema, state store (SQLite-backed), types (`Confidence` enum, `schema_version`, `NormalizedFinding`), `ConfidenceEngine` with deterministic promotion rules, recovery logic with `workflow_version` validation, `EngagementStore` with SQLite persistence via Drizzle, tests
- [ ] **Task 2.1:** Implement `src/argus/planner/` — types, `PlannerContext` with `findings` accumulation, capability-driven strategy (using `WorkflowRegistry` and `ToolRegistry`), `replan()` for dynamic phase insertion, deterministic fallback, tests
- [ ] **Task 2.2:** Implement `src/argus/evidence/` — types, `EvidenceManifest` with `package_hash`, collector (with storage limit enforcement, integrity verification), store (SQLite-backed artifact index via Drizzle, no JSON files), `/evidence prune --keep-last=N`, `/verify-package` command, tests
- [ ] **Task 2.3:** Implement `src/argus/reporting/` — `normalizer.ts` (tool-specific → `NormalizedFinding` conversion), generator (markdown/SARIF/JSON), templates, tests
- [ ] **Task 2.4:** Implement `src/argus/browser/` — `VerificationScenario` interface, engine, observer, verifiers (BOLA/XSS/PrivEsc implement `VerificationScenario`), credential loading from Task 0.3, tests

### Phase 3: CLI Integration (V5 CLI)

- [ ] **Task 3.1:** Wire `/assess` command — planner → bridge (with `WorkerSupervisor` from Task 0.11, error recovery from Task 0.4) → verifier (with credential file from Task 0.3) → evidence → report
- [ ] **Task 3.2:** Wire `/doctor` command — structured health checks across 6 categories (runtime, MCP live subprocess + ping, Playwright headless launch, LLM provider with `--online`, toolchain binary PATH validation, SQLite + WAL integrity), structured PASS/WARN/FAIL output, `--json` flag, per-check timeout
- [ ] **Task 3.3:** Wire `/verify`, `/report`, `/evidence` commands
- [ ] **Task 3.4:** Implement deterministic fallback for `/assess` (no LLM, no MCP)
- [ ] **Task 3.5:** Wire `/resume <engagement-id>` command — engagement store → planner → continue from last incomplete phase
- [ ] **Task 3.6:** Wire approval gates into `runPhase()` — check `approval_required` per phase, prompt or skip based on policy

### Phase 4: Safety & Rollback

- [ ] **Task 4.1:** Add feature flags — all default to `false`
- [ ] **Task 4.2:** Add destructive tool confirmation (interactive prompt, skip in `--auto`) — integrate with `ApprovalGate` from Task 0.9
- [ ] **Task 4.3:** Write E2E tests for Juice Shop, crAPI, DVWA, VAmPI

### Phase 5: Polish

- [ ] **Task 5.1:** Remove Python `argus-cli/` (after verifying TypeScript CLI is stable)
- [ ] **Task 5.2:** Update root `Makefile` and README for new CLI
- [ ] **Task 5.3:** `npm publish` first v5 release

---

## 9. Dependency Analysis

```
Module                   Depends On                          Depended By
──────────────────────────────────────────────────────────────────────────
argus/commands           planner, bridge, browser,           TUI
                         evidence, reporting, engagement,
                         workflows
argus/planner            bridge, workflows                   commands, engagement
argus/bridge             [subprocess: mcp_server.py]         commands, planner
argus/browser            evidence, [playwright npm]          commands
argus/evidence           [filesystem], [SQLite], engagement  browser, reporting
argus/reporting          evidence, engagement                commands
argus/workflows          [YAML filesystem]                   planner, commands
argus/engagement         [SQLite: better-sqlite3 + Drizzle]  commands, evidence,
                                                             reporting, recovery

Python Backend Modules:
state_machine.py         database/connection.py              orchestrator
intelligence_engine.py   cache.py, models/                   orchestrator
database/connection.py   [psycopg2 pool]                     all DB consumers
```

No circular dependencies. Coupling is moderate: commands depends on 5 modules, but this is expected for a CLI command dispatcher. All arrows point one direction.

---

## 10. Rollback Strategy

| Mechanism | How | When |
|-----------|-----|------|
| Feature flags | `browser_verification: false` | Any V5 feature causes issues |
| Git tags | `git tag v5-phase-1-complete` | Before each phase |
| Deterministic fallback | `/assess` works without LLM or MCP | AI or workers unavailable |
| Emergency release | `git checkout v4-stable` | Show-stopping bug |
| State machine safe transitions | `safe_transition()` skips invalid transitions | Concurrent worker race |
| Backend module isolation | Each B-phase task is independently revertible | Single task regression |

---

## 11. ADRs to Create

| ADR | Title | Key Decision |
|-----|-------|-------------|
| ADR-001 | MCP Transport Layer | stdio JSON-RPC subprocess vs TCP daemon |
| ADR-002 | Evidence Storage | Hybrid: SQLite (better-sqlite3 via Drizzle ORM, WAL mode) for all metadata, engagements, findings, evidence_packages, artifacts. Filesystem for binary blobs only. Per-package manifest.json for exportable integrity independent of DB. No JSON indexes, no state.json, no findings.json. |
| ADR-003 | Planner Decision Mode | Hybrid: LLM first, deterministic fallback |
| ADR-004 | Credential Management | JSON credential file vs env vars |
| ADR-005 | Error Recovery Policy | Per-phase retry/skip/fail matrix |
| ADR-006 | Backend Connection Pooling | Single pool always vs raw connections |
| ADR-007 | Threat Intel Caching | Redis-TTL vs in-memory vs no cache |
| ADR-008 | Future Multi-Agent Architecture | Reserved — single-agent for v5, architecture must support future delegation |
| ADR-009 | Feature Flag Strategy | Per-module activation (browser_verification, workflow_registry, engagement_store); all off by default in v5 |
| ADR-010 | Evidence Integrity | SHA256 per artifact is sufficient for v5; signature-based verification deferred until evidence sharing across orgs is required |
| ADR-011 | Credential Storage Evolution | `--creds` JSON file for v5; document future path to OS keychain, HashiCorp Vault, or encrypted secrets store |
| ADR-012 | Assessment Execution Model | Sequential workflow execution for v5; parallel DAG support reserved for v5.1 — phases execute in order, tools within a phase run concurrently when `execution: parallel` |
| ADR-013 | Capability Taxonomy | Canonical `Capability` enum in `capabilities.ts` — single source of truth: what a capability is, how it is named, how it is deprecated; YAML validation enforces enum membership |
| ADR-014 | Configuration Hierarchy | CLI flags > Environment variables > Project config (`./argus.config.yaml`) > User config (`~/.argus/config.yaml`) > Built-in defaults. Deep-merge objects, replace arrays. Workflow YAMLs excluded — they define the plan, not runtime config. |
| ADR-015 | Fork Boundary Enforcement | Argus modules depend only on symbols exported from public runtime entry points (`@opencode/runtime`). Direct imports into OpenCode implementation files or subdirectories are prohibited. Enforced via `no-restricted-imports` ESLint rule. |
| ADR-016 | LLM Availability & Fallback Strategy | Layered detection: Provider → Bridge → Planner. Typed `LLMUnavailableError`. Per-phase fallback to deterministic mode. Circuit breaker enters sticky `DEGRADED` after 3 failures in 10 minutes. Recovery probes re-enable LLM after cooldown. |

---

### Cross-Reference: Architecture Review → Tasks

| Review Finding | Task |
|----------------|------|
| MCP server not runnable (🔴 blocking) | Task 0.1 — `mcp_transport.py` |
| Missing child process lifecycle (🔴 blocking) | Task 0.2 — SIGTERM/SIGINT forwarding |
| Underspecified error recovery (🟡 major) | Task 0.4 — error recovery matrix |
| Missing credential management (🟡 major) | Task 0.3 — `--creds` flag + JSON schema |
| Playwright browser install (🟡 major) | Task 0.5 — postinstall + /doctor check |
| Cross-platform Python (🔵 minor) | Task 0.6 — `ARGUS_PYTHON` env var |
| Evidence cleanup policy (🔵 minor) | Task 2.2 — `/evidence prune` |
| JSON index concurrency (🔵 minor) | Task 2.2 — file locking |
| Missing ADRs | Task 0.7 — 16 ADR documents |
| JSON index reliability | Task 0.15 — SQLite replaces JSON indexes and state files |

### Cross-Reference: Architecture Gaps (from Design Review Feedback) → Tasks

| Design Gap | Task | Phase |
|------------|------|-------|
| Security Workflow Registry (Gap 1) | Tasks 0.10, 2.5 | 0, 2 |
| Finding Confidence Model (Gap 2) | Task 0.8, 2.6 | 0, 2 |
| Session Replay (Gap 3) | Tasks 2.6, 3.5 | 2, 3 |
| Assessment State Store (Gap 4) | Tasks 0.10, 2.6 | 0, 2 |
| Human Approval Gates (Gap 5) | Tasks 0.9, 3.6, 4.2 | 0, 3, 4 |
| Tool Capability Registry (Gap 6) | Tasks 0.10, 2.5 | 0, 2 |
| Multi-Agent Expansion Path (Gap 7) | ADR-008, Task 0.7 | 0 |
| Tool YAML tool coupling (Problem 1) | Tasks 0.10, 2.5 | 0, 2 |
| Confidence promotion rules (Problem 2) | Task 0.8, 2.6 | 0, 2 |
| Evidence chain integrity (Problem 3) | Task 2.2 | 2 |
| Planner context + replan (Problem 4) | Tasks 0.12, 2.1 | 0, 2 |
| Parallel/sequential execution (Problem 5) | Tasks 0.10, 2.5 | 0, 2 |
| Tool scoring/ranking (Problem 6) | Tasks 0.10, 2.5 | 0, 2 |
| Worker supervisor (Problem 7) | Task 0.11, 1.5 | 0, 1 |
| Normalized finding schema (Problem 8) | Task 0.13, 2.3 | 0, 2 |
| JSON index → SQLite migration (Q3) | Tasks 0.15, 2.2, 2.6 | 0, 2 |
| Capability taxonomy undefined (Risk 1) | Task 0.0.1, 2.5 | 0, 2 |
| Replan explosion (Risk 2) | Task 0.0.3, 2.1 | 0, 2 |
| Role-based credential schema (Risk 3) | Task 0.0.4, 0.3 | 0 |
| Evidence growth (Risk 4) | Tasks 2.2, 0.0.x | 2, 0 |
| Workflow versioning (Risk 5) | Task 0.0.2, 2.6 | 0, 2 |
| MCP tool drift (Risk 6) | Task 0.0.5, 1.5 | 0, 1 |

### Cross-Reference: Backend Review → Tasks

| Backend Gap | Task | Priority |
|-------------|------|----------|
| Connection leak in state machine | B.01 | P0 |
| CVE/EPSS caching missing | B.02 | P0 |
| Busy-wait in connection pool | B.03 | P1 |
| Retry backoff lacks jitter | B.04 | P1 |
| Global exception swallowing | B.05 | P1 |
| Missing OpenTelemetry | B.06 | P1 |
| Hardcoded GIT_HOST_ALLOWLIST | B.07 | P2 |
| Secrets at rest unencrypted | B.08 | P2 |
| CWE/OWASP mappings hardcoded | B.09 | P3 |
| No async I/O on hot paths | B.10 | P3 |
| Missing error taxonomy | B.11 | P3 |
| Constants.py module bloat | B.12 | P3 |
