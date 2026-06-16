# Argus Security Platform — AI Agent Operating Instructions

> **Architecture reference:** See `.opencode/ARCHITECTURE.md` for the full system architecture diagram, data flow, component tree, and design decisions. This file is the operating guide; ARCHITECTURE.md is the reference.

## Purpose

Argus is an autonomous security assessment platform built on top of OpenCode.

This repository contains the packaged `opencode` CLI with Argus as the security assessment layer. The `argus` binary launches the OpenCode TUI with `ARGUS_MODE=1`, which activates Argus-branded routes and slash commands.

## Entry Points

| Command | What it does |
|---------|-------------|
| `argus` | Launch Argus TUI (shows splash → enters OpenCode TUI with Argus routes) |
| `argus doctor` | Run health checks (Python, MCP worker, Playwright, DB, config, toolchain) |
| `argus assess <target>` | Run full autonomous security assessment |
| `argus report <id>` | Generate report for an engagement |
| `argus resume <id>` | Resume a paused/failed engagement |
| `argus verify <id>` | Re-run browser verification for a finding |
| `argus evidence <action>` | Browse/manage evidence packages |
| `argus config [filter]` | Show effective configuration |

**Binary:** `bin/argus` — `#!/usr/bin/env bun` wrapper that spawns `bun run src/argus/index.ts`

## Repository Structure

```
Argus-Tui/packages/opencode/     ← everything lives here
├── bin/argus                    ← installed global binary
├── src/
│   ├── index.ts                 ← OpenCode CLI entry point (the TUI host)
│   ├── argus/                   ← ALL security logic
│   │   ├── index.ts             ← Argus entry point (dashboard → spawns TUI)
│   │   ├── main.ts              ← Argus CLI (yargs-based, for doctor/assess/report etc)
│   │   ├── cli.ts               ← Yargs command definitions
│   │   ├── ui.ts                ← Terminal UI utilities (logo, styles, dashboard render)
│   │   ├── logo.ts              ← ARGUS ASCII logo glyphs
│   │   ├── intent-classifier.ts ← Slash detection + natural language → assessment/chat
│   │   ├── agent.ts             ← Facade re-exporting classifier, runner, commands
│   │   ├── workflow-runner.ts   ← Assessment executor (creates engagement, plans, executes)
│   │   ├── tui-commands.ts      ← Slash command definitions with handlers
│   │   ├── tui-command-registry.tsx ← SolidJS component registering commands in TUI keymap
│   │   ├── tui/
│   │   │   ├── navigator.ts     ← TUI route navigation helper
│   │   │   └── scan-store.ts    ← Reactive scan progress state (SolidJS store)
│   │   ├── commands/
│   │   │   ├── assess.ts        ← Full assessment orchestration
│   │   │   ├── doctor.ts        ← Health checks (runtime, python, MCP, Playwright, DB, creds, LLM, toolchain)
│   │   │   ├── report.ts        ← Report generation (markdown, JSON, SARIF, HTML)
│   │   │   ├── resume.ts        ← Resume engagement workflow
│   │   │   ├── verify.ts        ← Re-run browser verification
│   │   │   ├── evidence.ts      ← Evidence management (list, show, prune, verify)
│   │   │   ├── config.ts        ← Configuration display
│   │   │   └── approval.ts      ← Approval gates (re-export from workflows/approval)
│   │   ├── planner/
│   │   │   ├── planner.ts       ← WorkflowPlanner: selects workflow, creates phases
│   │   │   ├── executor.ts      ← InProcessExecutor: runs phases via MCP bridge
│   │   │   ├── planDeterministic.ts ← Hardcoded phase plans (when useLLM=false)
│   │   │   ├── strategy.ts      ← Target type/auth detection, capability deduction
│   │   │   ├── replan-rules.ts  ← Replan logic for inserting new capabilities
│   │   │   ├── capabilities.ts  ← Capability enum
│   │   │   └── types.ts         ← Planner types
│   │   ├── workflows/
│   │   │   ├── registry.ts      ← WorkflowRegistry: loads YAML workflows
│   │   │   ├── loader.ts        ← YAML loading + validation
│   │   │   ├── tool-registry.ts ← ToolRegistry: loads tool definitions, selects best tools
│   │   │   ├── approval.ts      ← ApprovalService: manages approval gates
│   │   │   ├── types.ts         ← Workflow definition types
│   │   │   └── *.yaml           ← Workflow definitions (full_assessment, quick_scan, etc.)
│   │   ├── bridge/
│   │   │   ├── mcp-client.ts    ← WorkersBridge: stdio JSON-RPC to Python MCP server
│   │   │   ├── supervisor.ts    ← WorkerSupervisor: restart logic
│   │   │   └── types.ts         ← Bridge types
│   │   ├── engagement/
│   │   │   ├── store.ts         ← EngagementStore: SQLite CRUD (Bun:sqlite + drizzle)
│   │   │   ├── types.ts         ← Engagement/phase status types
│   │   │   ├── schema.sql.ts    ← Drizzle schema definitions
│   │   │   ├── credentials.ts   ← CredentialStore: JSON file-based role credentials
│   │   │   ├── confidence.ts    ← ConfidenceEngine: promotes finding confidence
│   │   │   └── recovery.ts      ← Resume/retry validation
│   │   ├── evidence/
│   │   │   ├── store.ts         ← ArtifactStore: filesystem-backed evidence
│   │   │   ├── collector.ts     ← EvidenceCollector: saves requests/responses/screenshots
│   │   │   ├── integrity.ts     ← verifyPackage: SHA-256 hash verification
│   │   │   └── types.ts         ← Evidence types
│   │   ├── browser/
│   │   │   ├── engine.ts        ← PlaywrightEngine: browser automation
│   │   │   ├── types.ts         ← Verification scenario types
│   │   │   ├── login.ts         ← Login flow automation
│   │   │   ├── observer.ts      ← Page observation
│   │   │   └── verifiers/
│   │   │       ├── runner.ts    ← VerificationRunner: orchestrates verifiers
│   │   │       ├── bola.ts      ← BOLA verification
│   │   │       ├── xss.ts       ← Stored XSS verification
│   │   │       ├── priv-esc.ts  ← Privilege escalation verification
│   │   │       └── chained-scenario.ts ← Chained multi-step scenarios
│   │   ├── reporting/
│   │   │   ├── generator.ts     ← ReportGenerator: markdown/JSON/SARIF/HTML
│   │   │   ├── normalizer.ts    ← Finding normalization
│   │   │   └── types.ts         ← Report types
│   │   ├── config/
│   │   │   ├── loader.ts        ← Config loader
│   │   │   └── feature-flags.ts ← Feature flag system
│   │   └── shared/
│   │       ├── types.ts         ← Core types: Severity/Confidence enums, NormalizedFinding
│   │       └── capabilities.ts  ← Unified Capability enum
│   └── cli/cmd/tui/             ← OpenCode TUI presentation layer
│       ├── app.tsx              ← Main TUI app (route switching, Argus routes)
│       ├── routes/
│       │   └── home.tsx         ← Home screen (shows Argus logo + stats when ARGUS_MODE=1)
│       └── component/prompt/
│           └── index.tsx        ← Prompt input (handles Argus slash commands at line 1190)
```

---

## Architecture Rules

### Rule 1: Security Logic Lives Under `src/argus/`

All assessment, planning, execution, evidence, and reporting code belongs under `src/argus/`. The TUI layer under `src/cli/cmd/tui/` may import from `src/argus/` but never the reverse.

Verified locations:
- `src/argus/planner/` — planning
- `src/argus/workflows/` — workflow definitions + tool registry
- `src/argus/engagement/` — SQLite store + confidence
- `src/argus/evidence/` — filesystem evidence store
- `src/argus/browser/` — Playwright verification
- `src/argus/reporting/` — report generation
- `src/argus/bridge/` — MCP stdio bridge
- `src/argus/commands/` — CLI command handlers

### Rule 2: Assessment Flow

All assessments flow through:

```
User Input (TUI prompt or CLI)
  → intent-classifier.ts (classify / detect)
    → workflow-runner.ts (WorkflowRunner.run)
      → planner/planner.ts (WorkflowPlanner.plan)
        → workflows/registry.ts (WorkflowRegistry)
          → planner/executor.ts (InProcessExecutor.execute)
            → bridge/mcp-client.ts (WorkersBridge.callTool)
              → Python MCP worker (argus-workers/mcp_server.py)
                → tool execution (nuclei, nmap, etc.)
      → engagement/confidence.ts (ConfidenceEngine.promote)
      → engagement/store.ts (EngagementStore.saveFindings)
      → reporting/generator.ts (ReportGenerator.generateMarkdown)
```

### Rule 3: TUI Is Presentation Only

The TUI (`src/cli/cmd/tui/`) may:
- Accept user input
- Display findings, reports, progress
- Invoke Argus APIs (via `WorkflowRunner`, `doctorCommand`, etc.)

The TUI must not:
- Run scanners or tools directly
- Store evidence
- Calculate confidence
- Generate findings
- Perform workflow planning

Security logic executes in the MCP worker (Python), not in TypeScript React components.

### Rule 4: No Direct Tool Execution

Tools are never invoked directly from TypeScript. All scanning runs through:
```
WorkflowRunner → Planner → MCP Bridge → Python Worker → Tool Binary
```

The TypeScript layer only sends JSON-RPC requests to the Python MCP server (`argus-workers/mcp_server.py`), which manages tool lifecycle.

### Rule 5: SQLite Is The Source Of Truth

- Database: `~/.argus/argus.db` (SQLite with WAL mode)
- Evidence files: `~/.argus/engagements/` (screenshots, HAR, request/response dumps)
- Schema: `src/argus/engagement/schema.sql.ts` (Drizzle ORM)

Tables: `engagements`, `findings`, `phases`, `audit_log`, `tool_execution_log`, `evidence_packages`, `artifacts`, `workflow_snapshots`

### Rule 6: Confidence Levels

Defined in `src/argus/shared/types.ts`:

```typescript
enum Confidence {
  INFORMATIONAL = 0,  // No signal quality metadata
  LOW = 1,            // CANDIDATE tools (ffuf, nikto, passive recon)
  MEDIUM = 2,         // PROBABLE tools (dalfox, semgrep, gitleaks)
  HIGH = 3,           // CONFIRMED tools (sqlmap, browser verifier, nuclei CVE)
  VERIFIED = 4,       // Evidence exists
  CONFIRMED = 5,      // Finalized
}
```

Confidence is managed centrally by `ConfidenceEngine` in `src/argus/engagement/confidence.ts`. Never assign confidence manually.

### Rule 7: Slash Commands

Defined in `src/argus/tui-commands.ts`, registered in TUI keymap by `src/argus/tui-command-registry.tsx`.

| Command | Handler Location |
|---------|-----------------|
| `/assess <target>` | `src/argus/commands/assess.ts` → `WorkflowRunner` |
| `/recon <target>` | Same as assess with `useLLM: false` |
| `/doctor` | `src/argus/commands/doctor.ts` |
| `/status` | `src/argus/tui-commands.ts` inline handler |
| `/findings` | `src/argus/tui-commands.ts` inline handler |
| `/engagements` | `src/argus/tui-commands.ts` inline handler |
| `/tools` | `src/argus/tui-commands.ts` inline handler |
| `/workflows` | `src/argus/tui-commands.ts` inline handler |
| `/config` | `src/argus/commands/config.ts` |
| `/help` | `src/argus/tui-commands.ts` inline handler |

Implementation note: The TUI prompt at `src/cli/cmd/tui/component/prompt/index.tsx` lines 1190-1304 intercepts Argus slash commands before they reach the LLM. If the command has a handler in `tui-commands.ts`, it runs directly via `WorkflowRunner` or the command handler — the LLM is never involved. Results are streamed back via `sdk.client.session.prompt()`.

Custom slash commands can also be defined as Markdown files in:
- Project: `.opencode/commands/*.md`
- Global: `~/.config/opencode/commands/*.md`

These are loaded through the SDK server and appear in the TUI autocomplete, but they ARE sent to the LLM for execution.

### Rule 8: Natural Language Assessment Routing

The `intent-classifier.ts` detects assessment requests (e.g. "assess https://example.com", "find vulnerabilities in example.com") and routes them to `WorkflowRunner` — not to the LLM. General conversation continues through OpenCode.

### Rule 9: MCP Bridge Architecture

The TypeScript `WorkersBridge` (`src/argus/bridge/mcp-client.ts`) communicates with the Python MCP worker over stdio JSON-RPC:
- `list_tools` → returns tool definitions with capabilities and signal quality
- `call_tool` → executes a tool with parameters
- `ping` → health check

The Python worker (`argus-workers/mcp_server.py`) loads tool definitions from `argus-workers/tools/definitions/*.yaml` (46 tools) and manages their execution.

### Rule 10: Tool Definitions

The TypeScript `ToolRegistry` (`src/argus/workflows/tool-registry.ts`) loads from `src/argus/workflows/tool-definitions.yaml` (25 tools). This is a subset of the 46 tools the Python MCP worker knows about. Tools are selected by capability matching and gated by `requires` fields (tech_contains, target_scheme).

The toolchain check in `doctor.ts` dynamically scans `argus-workers/tools/definitions/` for the authoritative tool list and checks which are on the PATH.

### Rule 11: Evidence Is Mandatory

Every finding includes evidence (request, response, screenshot, HAR, tool output, timestamps). Evidence is stored to `~/.argus/engagements/` with SHA-256 integrity verification. Findings without evidence are never marked CONFIRMED.

### Rule 12: Testing

- TypeScript tests: `bun test test/argus/` (in `packages/opencode`)
- Python tests: `pytest tests/` (in `argus-workers`)
- Test files mirror source structure under `test/argus/unit/`

---

## Reference Documents

| Document | Path | Purpose |
|----------|------|---------|
| Architecture | `.opencode/ARCHITECTURE.md` | Full system architecture, data flow, diagrams |
| Agent guide | `.opencode/AGENTS.md` | (this file) Rules and operating instructions |

## Key Files Quick Reference

| Purpose | Path |
|---------|------|
| Argus entry | `src/argus/index.ts` |
| Argus CLI | `src/argus/main.ts` |
| Intent classifier | `src/argus/intent-classifier.ts` |
| Workflow runner | `src/argus/workflow-runner.ts` |
| Planner | `src/argus/planner/planner.ts` |
| Phase executor | `src/argus/planner/executor.ts` |
| Workflow registry | `src/argus/workflows/registry.ts` |
| Tool registry | `src/argus/workflows/tool-registry.ts` |
| MCP bridge | `src/argus/bridge/mcp-client.ts` |
| Engagement store | `src/argus/engagement/store.ts` |
| Evidence store | `src/argus/evidence/store.ts` |
| Confidence engine | `src/argus/engagement/confidence.ts` |
| Report generator | `src/argus/reporting/generator.ts` |
| Browser engine | `src/argus/browser/engine.ts` |
| Doctor command | `src/argus/commands/doctor.ts` |
| Assess command | `src/argus/commands/assess.ts` |
| TUI app | `src/cli/cmd/tui/app.tsx` |
| TUI home | `src/cli/cmd/tui/routes/home.tsx` |
| TUI prompt | `src/cli/cmd/tui/component/prompt/index.tsx` |
| Slash commands | `src/argus/tui-commands.ts` |
| TUI command registry | `src/argus/tui-command-registry.tsx` |
| Feature flags | `src/argus/config/feature-flags.ts` |
