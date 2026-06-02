# Argus V5 Design Document

**Date:** 2026-06-02
**Status:** Approved Design

## 1. Vision

```
Reason → Plan → Execute → Observe → React → Verify → Capture Evidence → Report
```

Argus V5 is a fork of [OpenCode](https://github.com/anomalyco/opencode) with cybersecurity superpowers. The TypeScript CLI (forked from OpenCode) provides the runtime foundation, provider-agnostic LLM access, TUI, and session management. Argus-specific modules add autonomous security workflows, browser-based verification, evidence collection, and professional reporting. Existing Python workers (`argus-workers/`) are accessed via the MCP protocol for tool execution.

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
│   │       └── commands/            # Security CLI commands
│   ├── package.json
│   └── tests/
│
├── argus-workers/                   # EXISTING — Python, preserved as-is
│   ├── mcp_server.py                # MCP protocol server
│   ├── tools/                       # 28 security tool wrappers
│   ├── agent/                       # ReAct agent
│   ├── llm_client.py                # Unified LLM client
│   └── ...
│
├── ARCHITECTURE_BOUNDARIES.md
└── Makefile
```

## 4. Decision Tree (15 Resolved Decisions)

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

## 5. Component Specifications

### 5.1 Planner (`src/argus/planner/`)

**Purpose:** Determine target type → attack surface → required workflow → required tools.

**Files:**

| File | Responsibility |
|------|---------------|
| `types.ts` | `TargetType`, `AuthState`, `Workflow`, `AssessmentPlan` types |
| `strategy.ts` | `detectTargetType(url, techStack?)`, `selectWorkflow(targetType, authState, techStack)` |
| `planner.ts` | `WorkflowPlanner.plan(target, context)`, `planDeterministic(target)` |

**Built-in workflows:**

| Workflow | Phases | Target |
|----------|--------|--------|
| `full_assessment` | recon → auth_detection → api_discovery → vuln_scan → verification → reporting | Web apps |
| `api_assessment` | recon → auth_detection → api_discovery → bola_testing → verification → reporting | APIs |
| `quick_scan` | recon → vuln_scan → reporting | Passive/no-LLM mode |
| `browser_assessment` | recon → browser_scan → auth_detection → verification → reporting | SPAs |

**Fallback:** When LLM unavailable, `planDeterministic()` uses URL regex patterns (`/api/`, `.json`, known SPA tech) to select workflow.

### 5.2 MCP Bridge (`src/argus/bridge/`)

**Purpose:** IPC between TypeScript CLI and Python workers.

**Files:**

| File | Responsibility |
|------|---------------|
| `mcp-client.ts` | `WorkersBridge.connect()`, `callTool()`, `getTools()` |
| `types.ts` | `ToolResult`, `ToolDefinition`, `MCPError` types |

**Transport:**
- Spawn `python3 <workers-path>/mcp_server.py` as subprocess
- Communication via stdio JSON-RPC
- Fall back to deterministic mode if spawn fails or no Python found

### 5.3 Browser/Observe & React (`src/argus/browser/`)

**Purpose:** Dynamically interact with web apps, observe behavior, verify findings.

**Files:**

| File | Responsibility |
|------|---------------|
| `engine.ts` | `PlaywrightEngine` — wraps Playwright, captures screenshots and HAR |
| `observer.ts` | `ObserveLoop.observe(url)` → `Observation`, `compareObservations(a, b)` → `diff` |
| `verifier.ts` | `BOLAVerifier`, `StoredXSSVerifier`, `PrivilegeEscalationVerifier` — each returns `VerifierResult` |

**BOLA Workflow:**

```
BOLAVerifier.verify(endpoint, credsA, credsB, idParam, idA, idB)
  → Login as User A → navigate to /resource/ID_A → capture screenshot
  → Logout → Login as User B → navigate to /resource/ID_A → capture screenshot
  → Compare observations → data_exposed? → VerifierResult
```

**Stored XSS Workflow:**

```
StoredXSSVerifier.verify(injectUrl, payload, victimViewUrl)
  → Navigate to injectUrl → inject payload → submit
  → Navigate to victimViewUrl → observe DOM → payload_executed?
  → Screenshot → VerifierResult
```

**Privilege Escalation Workflow:**

```
PrivilegeEscalationVerifier.verify(targetUrl, lowPrivCreds, highPrivEndpoint)
  → Login as low-priv user → navigate to high-priv endpoint
  → Observe response (200 vs 403) → access_granted?
  → Screenshot → VerifierResult
```

### 5.4 Evidence Engine (`src/argus/evidence/`)

**Purpose:** Capture evidence for every confirmed finding. Automatic during verification.

**Files:**

| File | Responsibility |
|------|---------------|
| `types.ts` | `ArtifactType`, `Artifact` (with SHA256 integrity), `EvidencePackage` |
| `collector.ts` | `EvidenceCollector.saveRequest()`, `saveResponse()`, `captureScreenshot()` |
| `store.ts` | `ArtifactStore.createPackage()`, `getPackage()`, `listPackages()` — filesystem + JSON index |

**Storage layout:**

```
~/.argus/artifacts/
├── find-001-bola/
│   ├── screenshots/user-a-view.png
│   ├── screenshots/user-b-replay.png
│   ├── requests/request.txt
│   └── responses/response.txt
├── find-002-xss/
│   └── ...
└── index.json                    # Global artifact index
```

### 5.5 Reporting (`src/argus/reporting/`)

**Purpose:** Generate professional reports with embedded evidence.

**Files:**

| File | Responsibility |
|------|---------------|
| `generator.ts` | `ReportGenerator.generateMarkdown()`, `generateHTML()`, `generateSARIF()`, `generateJSON()` |
| `templates/` | Jinja2-style HTML template (future), Markdown template |

**Markdown report structure:**

```markdown
# Argus Security Assessment Report
Target: https://target.com | Date: 2026-06-02

## Summary
| Severity | Count | Verified |
| Critical | 1     | ✅       |
| High     | 2     | ✅       |

## Findings
### CRITICAL: BOLA in /api/users/{id}
- Endpoint: GET /api/users/42
- Verified: ✅ Confirmed via browser replay
- Evidence: screenshots/ (2), requests/ (1), responses/ (1)

## Evidence Artifacts
- find-001-bola/screenshots/user-a-view.png
- find-001-bola/screenshots/user-b-replay.png
```

### 5.6 CLI Commands

| Command | Function | Builder |
|---------|----------|---------|
| `/assess <target>` | Full autonomous assessment | Planner → MCP bridge → Browser verifier → Evidence → Report |
| `/doctor` | Health checks | Checks: OpenCode runtime, MCP bridge, Playwright, tools in PATH |
| `/verify <finding-id>` | Re-run browser verification | Browser verifier only, reuses existing evidence package |
| `/report [format]` | Generate/regenerate report | Report generator, reads from ArtifactStore |
| `/evidence [list/show]` | Browse captured evidence | ArtifactStore queries |

Existing OpenCode commands (`/scan`, `/recon`, `/auth`, `/api`) map to direct MCP tool calls, bypassing the planner.

## 6. Implementation Tasks

### Phase 1: Foundation
- [ ] Task 1.1: Clone OpenCode into `cli/`, verify `argus --help` works
- [ ] Task 1.2: Rename package to `argus` in `package.json`, update all branding
- [ ] Task 1.3: Create `ARCHITECTURE_BOUNDARIES.md`
- [ ] Task 1.4: Set up GitHub Actions (lint → typecheck → unit tests)
- [ ] Task 1.5: Write `src/argus/bridge/mcp-client.ts` — subprocess MCP connection

### Phase 2: Core Modules
- [ ] Task 2.1: Implement `src/argus/planner/` — types, strategy, planner, tests
- [ ] Task 2.2: Implement `src/argus/evidence/` — types, collector, store, tests
- [ ] Task 2.3: Implement `src/argus/reporting/` — generator, markdown output, tests
- [ ] Task 2.4: Implement `src/argus/browser/` — engine, observer, verifiers, tests

### Phase 3: CLI Integration
- [ ] Task 3.1: Wire `/assess` command — planner → bridge → verifier → evidence → report
- [ ] Task 3.2: Wire `/doctor` command — health checks
- [ ] Task 3.3: Wire `/verify`, `/report`, `/evidence` commands
- [ ] Task 3.4: Implement deterministic fallback for `/assess` (no LLM, no MCP)

### Phase 4: Safety & Rollback
- [ ] Task 4.1: Add feature flags — all default to `false`
- [ ] Task 4.2: Add destructive tool confirmation (interactive prompt, skip in `--auto`)
- [ ] Task 4.3: Write `__tests__/e2e/juice-shop.test.ts`, `crapi.test.ts`, etc.

### Phase 5: Polish
- [ ] Task 5.1: Remove Python `argus-cli/` (after verifying TypeScript CLI is stable)
- [ ] Task 5.2: Update root `Makefile` and README for new CLI
- [ ] Task 5.3: `npm publish` first v5 release

## 7. Rollback Strategy

| Mechanism | How | When |
|-----------|-----|------|
| Feature flags | `browser_verification: false` | Any V5 feature causes issues |
| Git tags | `git tag v5-phase-1-complete` | Before each phase |
| Deterministic fallback | `/assess` works without LLM or MCP | AI or workers unavailable |
| Emergency release | `git checkout v4-stable` | Show-stopping bug |
