# Argus Architecture

> AI-powered security assessment platform built on OpenCode's TUI engine with a Python/MCP worker backend.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Two-Process Architecture](#two-process-architecture)
3. [TUI Component Tree](#tui-component-tree)
4. [Assessment Flow](#assessment-flow)
5. [MCP Bridge Architecture](#mcp-bridge-architecture)
6. [Data Model](#data-model)
7. [Workflow System](#workflow-system)
8. [Tool Registry](#tool-registry)
9. [Capabilities System](#capabilities-system)
10. [Slash Command Resolution](#slash-command-resolution)
11. [Evidence Integrity](#evidence-integrity)
12. [Configuration](#configuration)
13. [Feature Flags](#feature-flags)
14. [Error Recovery](#error-recovery)
15. [Health Checks](#health-checks)
16. [Key Design Decisions](#key-design-decisions)

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                          User (terminal)                             │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                       ┌────────▼────────┐
                       │   bin/argus     │   #!/usr/bin/env bun
                       │  (global bin)   │   spawns bun run src/argus/index.ts
                       └────────┬────────┘
                                │
              ┌─────────────────▼──────────────────┐
              │        src/argus/index.ts           │
              │        (Argus CLI entry point)      │
              │                                     │
              │  No args?  -> launchTui()            │
              │  Has args? -> yargs dispatch         │
              └──────────┬──────────────┬───────────┘
                         │              │
              ─ CLI mode ─              ─ TUI mode ─
                         │              │
          ┌──────────────▼──┐   ┌───────▼────────────────────┐
          │ src/argus/main.ts│   │  spawn child process       │
          │ (yargs commands) │   │  bun run --conditions=browser│
          │                  │   │    src/index.ts            │
          │  doctor          │   │    run --interactive       │
          │  assess          │   │  env: ARGUS_MODE=1         │
          │  report          │   └───────┬────────────────────┘
          │  resume          │           │
          │  verify          │   ┌───────▼────────────────────┐
          │  evidence        │   │  src/index.ts              │
          │  config          │   │  (OpenCode CLI entry point)│
          └──────────────────┘   └───────┬────────────────────┘
                                         │
                                 ┌───────▼────────────────────┐
                                 │  run.ts                    │
                                 │  -> runInteractiveMode()    │
                                 │  -> runInteractiveLocal()   │
                                 └───────┬────────────────────┘
                                         │
                                 ┌───────▼────────────────────┐
                                 │  runtime.ts                │
                                 │  -> createRuntimeLifecycle()│
                                 └───────┬────────────────────┘
                                         │
                                 ┌───────▼────────────────────┐
                                 │  runtime.lifecycle.ts      │
                                 │  -> createCliRenderer()    │
                                 │  -> RunFooter              │
                                 │  -> entrySplash()          │
                                 └───────┬────────────────────┘
                                         │
                                 ┌───────▼────────────────────┐
                                 │  app.tsx (SolidJS TUI App) │
                                 │                            │
                                 │  Routes:                   │
                                 │  home       -> Home.tsx     │
                                 │  session    -> Session     │
                                 │  scan       -> ScanDashboard│
                                 │  findings   -> FindingsViewer│
                                 │  engagements-> EngagementBrowser│
                                 │  workspace  -> Workspace    │
                                 └────────────────────────────┘
```

**Entry condition logic:**

| Invocation | Behaviour |
|---|---|
| `argus` (no args) | Spawns OpenCode TUI child process with `ARGUS_MODE=1` |
| `argus assess <target>` | Dispatches directly to yargs handler in `main.ts` |
| `argus doctor` | Runs health checks, prints report, exits |
| `argus report <id>` | Generates report for engagement ID (markdown/json/sarif/html) |
| `argus verify <finding-id>` | Re-runs browser verification for a specific finding |
| `argus evidence <action>` | Evidence management (list, show, prune, verify-package) |
| `argus config [filter]` | Shows effective configuration |
| `argus resume <engagement-id>` | Resumes a paused or failed engagement |

---

## Two-Process Architecture

Argus uses a **two-process architecture** to keep its extensions cleanly isolated from OpenCode internals.

### Process 1 - Argus CLI Wrapper (`src/argus/index.ts`)

Entry point for the `argus` binary. Responsibilities:
- Parse CLI arguments via yargs
- If **no arguments**: spawn the OpenCode TUI as a child process with `ARGUS_MODE=1`
- If **arguments present**: dispatch to yargs command handlers for one-shot execution

### Process 2 - OpenCode TUI (child process)

Runs `src/index.ts` with `run --interactive` and `--conditions=browser` (activates bun's SolidJS plugin for JSX transformation).

When `ARGUS_MODE=1` is set, the TUI:
- Renders Argus-branded entry splash (logo from `src/argus/logo.ts`)
- Mounts `Home.tsx` (shows Argus logo, engagement stats, quick actions)
- Registers Argus slash commands via `ArgusCommandRegistry`
- Enables Argus-specific routes: `scan`, `findings`, `engagements`, `workspace`

---

## TUI Component Tree (SolidJS)

```
<OpencodeKeymapProvider>
  <RouteProvider>
    <App>
      |
      +-- <ArgusCommandRegistry />
      |     +-- Registers /assess, /scan, /recon, /doctor, etc. in keymap
      |
      +-- Route: home -> <Home />
      |     +-- Argus logo (from src/argus/logo.ts)
      |     +-- Summary stats bar (targets, active engagements, findings)
      |     +-- Quick action labels
      |     +-- Recent engagements list (loaded from EngagementStore)
      |     +-- System status indicators
      |     +-- <Prompt /> (slash autocomplete, NL detection, submit handler)
      |
      +-- Route: session -> <Session />
      |     +-- Conversation view (proxied to OpenCode LLM session)
      |
      +-- Route: scan -> <ScanDashboard />
      |     +-- Live phase-by-phase assessment progress
      |
      +-- Route: findings -> <FindingsViewer />
      |     +-- Findings filtered by severity/confidence
      |
      +-- Route: engagements -> <EngagementBrowser />
      |     +-- Paginated engagement list with status badges
      |
      +-- Route: workspace -> <Workspace />
            +-- (assessment workspace pass-through)
```

---

## Assessment Flow

```
User types "/assess https://example.com"
  |
  +-> prompt/index.tsx (submit handler)
        |
        +-> findArgusTuiCommand("assess") -> FOUND in tui-commands.ts
        |     |
        |     |   <- LLM is NOT involved for TUI commands
        |     |
        |     +-> store.createEngagement(target)
        |     +-> navigateTo({ type: "scan", engagementId })
        |     +-> WorkflowRunner.run({ target, useLLM: true })
        |
        +-> (if NOT found) -> OpenCode SDK Markdown commands -> LLM


WorkflowRunner.run(target, options)
  |
  +-[1] EngagementStore.createEngagement()
  |       +-> Insert row in SQLite engagements table
  |
  +-[2] WorkflowRegistry.loadAll()
  |       +-> Parse src/argus/workflows/*.yaml
  |
  +-[3] ToolRegistry.load()
  |       +-> Parse src/argus/workflows/tool-definitions.yaml
  |
  +-[4] WorkflowPlanner.plan(target)
  |       |
  |       +-> detectTargetType(target)        -> "web_app"|"api"|"spa"|"unknown"
  |       +-> detectAuthState(target)         -> "none"|"basic"|"session"|"oauth"|"jwt"
  |       +-> determineRequiredCapabilities()
  |       +-> workflowRegistry.findByCapabilities() -> best-matching workflow
  |       |
  |       +-> (useLLM=false) -> planDeterministic()
  |       |
  |       +-> For each phase:
  |             +-> toolRegistry.selectBest(capabilities) -> ranked tools
  |             +-> If zero tools && !fail_fast -> skip phase
  |
  +-[5] WorkersBridge.connect()
  |       +-> Spawn Python MCP worker (argus-workers/mcp_server.py)
  |
  +-[6] For each phase -> for each tool:
  |       +-> bridge.callTool(toolName, args)    <- JSON-RPC over stdio
  |       +-> confidenceEngine.promote(finding)
  |       +-> store.savePhase()
  |       |
  |       +-> (if BROWSER_VERIFICATION enabled && credentials available)
  |             +-> runBrowserVerifiers()
  |                   +-> BOLA verifier (Playwright)
  |                   +-> Stored XSS verifier (Playwright)
  |                   +-> PrivEsc verifier (Playwright)
  |
  +-[7] store.saveFindings()
  +-[8] bridge.disconnect()
  +-[9] ReportGenerator.generateMarkdown()
  +-[10] Report written to stdout
```

### Confidence Promotion Pipeline

Findings start at a baseline confidence derived from the tool's `signal_quality`, then promoted by `ConfidenceEngine` (`src/argus/engagement/confidence.ts`):

| Level | Value | Meaning |
|---|---|---|
| `INFORMATIONAL` | 0 | No signal quality metadata |
| `LOW` | 1 | `CANDIDATE` tools (ffuf, nikto, passive recon) |
| `MEDIUM` | 2 | `PROBABLE` tools (dalfox, semgrep, gitleaks) |
| `HIGH` | 3 | `CONFIRMED` tools (sqlmap, browser verifier, nuclei CVE) |
| `VERIFIED` | 4 | Evidence attached (screenshot, request/response) |
| `CONFIRMED` | 5 | Finalized (requires human review) |

Promotion rules (from `src/argus/engagement/confidence.ts`):
- `INFORMATIONAL -> LOW`: always (default minimum)
- `LOW -> MEDIUM`: if tool is known AND severity >= 2
- `MEDIUM -> HIGH`: if CWE/OWASP mapped OR HTTP 2xx on auth endpoint
- `HIGH -> VERIFIED`: if evidence package exists
- `VERIFIED -> CONFIRMED`: never automated

---

## MCP Bridge Architecture

```
+----------------------+    JSON-RPC 2.0 over stdio    +--------------------------+
|    TypeScript        | -------------------------->   |   Python MCP Worker      |
|                      |                               |   (mcp_server.py)        |
|    WorkersBridge     |  Request:                     |                          |
|    (bridge/          |  {                            |   Loads tool definitions |
|     mcp-client.ts)   |    "jsonrpc": "2.0",          |   from:                  |
|                      |    "id": "1",                 |   tools/definitions/     |
|                      |    "method": "call_tool",     |   *.yaml (46 tools)      |
|                      |    "params": {                |                          |
|                      |      "name": "nuclei",        |   Executes system        |
|                      |      "arguments": { ... }     |   binaries via subprocess|
|                      |    }                          |                          |
|                      |  }                            |                          |
|                      |                               |  Returns:                |
|                      | <---------------------------  |  { content[],            |
|                      |  Response:                    |    isError,              |
|                      |  {                            |    meta: {               |
|                      |    "jsonrpc": "2.0",          |      success,            |
|                      |    "id": "1",                 |      duration_ms,        |
|                      |    "result": {                |      signal_quality } }  |
|                      |      "content": [...],        |                          |
|                      |      "isError": false,        |                          |
|                      |      "meta": {                |                          |
|                      |        "success": true,       |                          |
|                      |        "duration_ms": 12345,  |                          |
|                      |        "signal_quality":      |                          |
|                      |          "CONFIRMED"          |                          |
|                      |      }                        |                          |
|                      |    }                          |                          |
|                      |  }                            |                          |
+----------------------+                               +--------------------------+

Resilience features:
  - Circuit breaker: 3 failures -> 5-minute cooldown
  - Drift detection: periodic SHA-256 hash comparison of tool names + capabilities
  - Signal forwarding: SIGTERM/SIGINT to child process
  - Request timeout: 10min default (configurable)
  - Max pending requests: 10 concurrent

Bridge methods:
  connect()       -> validate paths, spawn python, wait for ready
  callTool()      -> send JSON-RPC, transform response to ToolResult
  getTools()      -> return ToolDefinition[] with capabilities + signal_quality
  isHealthy()     -> ping/pong
  quickDriftCheck() -> SHA-256 hash comparison
  detectDrift()  -> full comparison (missing tools, capability gaps)
  disconnect()   -> SIGTERM child, cleanup
```

---

## Data Model

### SQLite Database (`~/.argus/argus.db`)

```
engagements
  id              TEXT PRIMARY KEY       (ENG-{timestamp36}-{uuid4})
  target          TEXT NOT NULL
  workflow        TEXT NOT NULL
  workflow_version INTEGER DEFAULT 1
  status          TEXT DEFAULT 'CREATED' (CREATED|RUNNING|PAUSED|COMPLETED|FAILED)
  schema_version  INTEGER DEFAULT 1
  created_at      INTEGER               (Unix ms)
  updated_at      INTEGER

findings
  id              TEXT PRIMARY KEY
  engagement_id   TEXT NOT NULL -> engagements(id)
  title           TEXT NOT NULL
  severity        INTEGER NOT NULL      (0=INFO 1=LOW 2=MEDIUM 3=HIGH 4=CRITICAL)
  confidence      INTEGER NOT NULL      (0=INFORMATIONAL ... 5=CONFIRMED)
  status          TEXT DEFAULT 'PENDING' (PENDING|CONFIRMED|REJECTED|FINALIZED)
  description     TEXT
  subtype         TEXT, cve TEXT, cwe TEXT, owasp TEXT
  remediation     TEXT
  tool            TEXT, phase TEXT
  created_at      INTEGER, updated_at INTEGER, finalized_at INTEGER
  INDEXES: engagement_id, status, severity

phases
  id              TEXT PRIMARY KEY
  engagement_id   TEXT NOT NULL -> engagements(id)
  name            TEXT NOT NULL
  status          TEXT DEFAULT 'PENDING'
  capabilities    TEXT DEFAULT '[]'      (JSON array)
  execution_mode  TEXT
  started_at      INTEGER, completed_at INTEGER
  error           TEXT
  replan_cycle    INTEGER DEFAULT 0

audit_log
  id              TEXT PRIMARY KEY
  engagement_id   TEXT NOT NULL -> engagements(id)
  event_type      TEXT NOT NULL
  message         TEXT NOT NULL
  metadata        TEXT DEFAULT '{}'
  created_at      INTEGER

evidence_packages
  id              TEXT PRIMARY KEY
  finding_id      TEXT NOT NULL -> findings(id)
  package_hash    TEXT NOT NULL
  created_at      INTEGER

artifacts
  id              TEXT PRIMARY KEY
  package_id      TEXT NOT NULL -> evidence_packages(id)
  path            TEXT NOT NULL
  sha256          TEXT NOT NULL
  size_bytes      INTEGER NOT NULL
  type            TEXT NOT NULL          (request|response|screenshot|har|log)
```

### Evidence Filesystem (`~/.argus/engagements/`)

```
~/.argus/engagements/
+-- ENG-{id}/
    +-- artifacts/
        +-- {finding-id}/
            +-- manifest.json              (SHA-256 signed)
            +-- requests/
            |   +-- request-{ts}.txt
            +-- responses/
            |   +-- response-{ts}.txt
            +-- screenshots/
                +-- screenshot-{ts}.png
```

---

## Workflow System

### Workflow YAML Structure

```yaml
name: full_assessment
label: Full Web Assessment
version: 1
phases:
  - name: recon
    required_capabilities: [web_recon, port_scanning, technology_detection]
    execution: parallel
    error_recovery: retry_once_then_skip
  - name: vuln_scan
    required_capabilities: [vulnerability_scanning, template_scanning]
    execution: parallel
    error_recovery: retry_once_then_skip
  - name: reporting
    required_capabilities: [report_generation]
    execution: sequential
    error_recovery: skip_and_continue
approval_required:
  destructive_tools: true
  auth_testing: false
  privilege_escalation: true
```

### Available Workflows

Stored in `src/argus/workflows/*.yaml`. Loaded by `WorkflowRegistry` (`src/argus/workflows/registry.ts`).

| File | Label | Phases |
|---|---|---|
| `full_assessment.yaml` | Full Web Assessment | recon, auth_detection, api_discovery, vuln_scan, verification, reporting |
| `quick_scan.yaml` | Quick Passive Scan | recon, vuln_scan, reporting |
| `api_assessment.yaml` | API Security Assessment | recon, auth_detection, api_discovery, bola_testing, verification, reporting |
| `browser_assessment.yaml` | Browser-Based SPA | recon, browser_scan, auth_detection, verification, reporting |
| `bola.yaml` | BOLA Assessment | setup_sessions, resource_access_check, evidence_collection |
| `xss.yaml` | XSS Assessment | injection, victim_view, evidence_collection |
| `privilege_escalation.yaml` | PrivEsc Assessment | auth_bypass_check, endpoint_access_check, evidence_collection |

---

## Tool Registry

### TypeScript-side (`src/argus/workflows/tool-definitions.yaml`)

25 tool definitions for the **planner** capability matching. Schema:

```
ToolDef:
  name, label, capabilities[]
  requires_auth, destructive, timeout_seconds
  scoring: { confidence_score, coverage_score }
  signal_quality: CONFIRMED|PROBABLE|CANDIDATE
  requires: { tech_contains?, target_scheme? }
  priority?, cost: low|medium|high
```

### Python-side (`argus-workers/tools/definitions/*.yaml`)

46 individual tool YAML files with runtime configuration for the MCP worker:

```yaml
name: nuclei
command: nuclei
description: "Nuclei vulnerability scanner"
args: ["-json", "-silent"]
parameters:
  - name: target
    type: string
    required: true
    flag: "-u"
capabilities: [vulnerability_scanning, template_scanning]
signal_quality: CONFIRMED
priority: 95
cost: medium
enabled: true
timeout: 600
```

The doctor's toolchain check (`src/argus/commands/doctor.ts`) dynamically scans `argus-workers/tools/definitions/` for the authoritative tool list.

---

## Capabilities System

Defined in `src/argus/shared/capabilities.ts`.

```
Recon:        WEB_RECON, PORT_SCANNING, TECHNOLOGY_DETECTION, CONTENT_DISCOVERY, HTTP_PROBE
Vuln Scan:    VULNERABILITY_SCANNING, TEMPLATE_SCANNING, SSRF_CHECK, SQLI_DETECTION, DATABASE_EXFILTRATION
Auth:         AUTH_DETECTION, CREDENTIAL_ANALYSIS, JWT_ANALYSIS
API:          API_PROBING
Browser:      BROWSER_VERIFICATION
Reporting:    REPORT_GENERATION
```

---

## Slash Command Resolution

```
User types "/assess https://example.com"
  |
  +-> prompt/index.tsx submit handler
        |
        +-[1] findArgusTuiCommand("assess")
        |       |
        |       +-> FOUND in tui-commands.ts: run handler (NO LLM)
        |       |     /assess,/scan,/recon -> WorkflowRunner
        |       |     /doctor             -> doctorCommand()
        |       |     others              -> argusCmd.handler()
        |       |
        |       +-> NOT FOUND: check Markdown command files
        |             .opencode/commands/*.md
        |             ~/.config/opencode/commands/*.md
        |
        +-[2] Not found in either: natural language check
               classify() detects assessment? -> WorkflowRunner
               otherwise -> LLM via session.prompt()
```

Command priority:
1. Argus built-in (`src/argus/tui-commands.ts`) via `ArgusCommandRegistry`
2. Project Markdown commands (`.opencode/commands/*.md`)
3. Global Markdown commands (`~/.config/opencode/commands/*.md`)
4. LLM fallback

---

## Evidence Integrity

### Creation

```
For each artifact: hash = SHA256(contents)

manifest.json:
  { package_id, engagement_id, created_at,
    artifacts: [{ path, hash, type, size_bytes }],
    package_hash: SHA256(manifest_json + all artifact_hashes) }
```

### Verification (`src/argus/evidence/integrity.ts`)

```
For each artifact: re-hash file, compare to manifest hash
Recompute package_hash from manifest + artifact hashes
Compare to stored package_hash
Mismatch = tampered/corrupted
```

---

## Configuration

Precedence: CLI flags > Environment > Project config > User config > Defaults

| Source | Location |
|---|---|
| CLI flags | `--enable-browser`, `--deterministic` |
| Environment | `ARGUS_PYTHON`, `ARGUS_CREDS_PATH`, `ARGUS_DB_PATH`, `ARGUS_WORKERS_PATH` |
| Project config | `./argus.config.yaml` |
| User credentials | `~/.argus/credentials.json` |
| OpenCode providers | `$XDG_DATA_HOME/opencode/auth.json` |
| Global commands | `~/.config/opencode/commands/*.md` |
| Project commands | `.opencode/commands/*.md` |

---

## Feature Flags

Defined in `src/argus/config/feature-flags.ts`. All default off.

| Flag | CLI flag | Purpose |
|---|---|---|
| `BROWSER_VERIFICATION` | `--enable-browser` | Playwright-based BOLA/XSS/PrivEsc |
| `WORKFLOW_REGISTRY` | `--enable-workflow-registry` | Capability-based planning |
| `ENGAGEMENT_STORE` | `--enable-engagement-store` | SQLite persistence |
| `APPROVAL_GATES` | `--enable-approval-gates` | Interactive approval prompts |

---

## Error Recovery

Per-phase strategy in workflow YAMLs:

| Strategy | Behaviour |
|---|---|
| `retry_once_then_skip` | Retry once, skip phase if still failing |
| `skip_and_continue` | Skip phase if no tools match (planner drops it) |
| `fail_fast` | Abort entire assessment |

---

## Health Checks

`argus doctor` runs 8 checks:

1. Runtime - Node.js version + platform
2. Python - discover python3 via PATH or `$ARGUS_PYTHON`
3. MCP Worker - spawn mcp_server.py, connect, ping
4. Playwright - npx playwright --version
5. Database - open ~/.argus/argus.db, engagement count
6. Credentials - check ~/.argus/credentials.json exists
7. Configuration - env vars, OpenCode provider registry
8. Toolchain - scan argus-workers/tools/definitions/*.yaml, check each on PATH

---

## Key Design Decisions

1. **Two-process architecture**: Argus wrapper + OpenCode TUI as separate OS processes. Keeps Argus changes isolated from OpenCode internals.

2. **MCP over stdio**: JSON-RPC bridge to Python worker. New tools = new YAML file, no TypeScript changes.

3. **SQLite + filesystem**: Structured data in SQLite, artifacts on filesystem. No infrastructure dependencies, works offline.

4. **Feature flags default off**: Advanced features opt-in. Minimal default path.

5. **Confidence via promotion pipeline**: Start conservative, promote with evidence/tool corroboration/browser PoC. Reduces false positives.

6. **Capability-based planning**: Workflows declare capabilities, tools declare capabilities. Planner matches at runtime. Decouples "what" from "how."

7. **Evidence integrity via SHA-256**: Every artifact hashed at creation. Manifest hash chains artifact hashes. `argus verify <finding-id>` detects tampering.
