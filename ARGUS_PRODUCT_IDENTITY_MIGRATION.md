# Argus Product Identity Migration Plan

## Goal
Replace OpenCode's coding-assistant TUI with an assessment-centric Argus TUI while reusing all existing TUI infrastructure (`@opentui/solid`, `@opentui/core`, routing, keymaps, dialogs, rendering pipeline).

## Current Architecture

```
User types:  argus doctor | argus assess <target> | bun dev
                 │                  │                     │
                 ▼                  ▼                     ▼
         src/argus/main.ts   src/argus/main.ts      src/index.ts
         (CLI only)          (CLI only)             (yargs CLI)
                                                       │
                                                       ▼
                                              .command(ArgusAssessCommand)
                                              .command(ArgusDoctorCommand)
                                              .command(...)
                                              .command(RunCommand) ← TUI entry
                                                       │
                                                       ▼
                                              src/cli/cmd/run.ts
                                              (prompt → LLM → stream response)
                                                       │
                                                       ▼
                                              src/cli/cmd/tui/app.tsx
                                              (SolidJS TUI with routes:
                                                Home, Session)
                                                       │
                                                       ▼
                                              Routes:
                                                /home    → prompt input + LLM chat
                                                /session → conversation view
```

The TUI is a **coding assistant**: user types a prompt, it streams an LLM response, they chat back and forth. The Argus commands are CLI-only sidecars bolted onto the same yargs parser.

---

## Target Architecture

```
User types:  argus                          argus scan <target>
                 │                                │
                 ▼                                ▼
         src/index.ts (rebranded)          src/argus/commands/assess.ts
         (yargs → TUI launcher)            (already exists)
                 │
                 ▼
         ┌─────────────────────────────────┐
         │        ARGUS TUI                │
         │  (reuses @opentui/solid,        │
         │   @opentui/core, keymaps,       │
         │   rendering pipeline, dialogs)  │
         │                                 │
         │  Routes:                        │
         │   /dashboard   → scan history   │
         │   /scan        → live scan view │
         │   /findings    → findings browser│
         │   /report      → report view    │
         │   /settings    → config         │
         │   /terminal    → raw CLI access │
         └─────────────────────────────────┘
                 │
                 ▼
         OpenCode Runtime (internal)
         ├── Provider/LLM system
         ├── Session management
         ├── Storage/Database
         ├── Plugin system
         ├── MCP client
         └── Effect system
```

**OpenCode becomes an invisible runtime layer** — like React is to a web app. The user never sees "OpenCode." They see "Argus."

---

## Migration Phases

### Phase 1: Branding & Entry Point ✅ COMPLETED

**Objective:** When users run `argus` with no arguments, they see the Argus splash (not the OpenCode coding assistant).

**Completed work:**

1. **Created `src/argus/index.ts` — Argus CLI entry point**
   - Standalone yargs CLI with only Argus commands (assess, doctor, report, resume, verify, evidence, config)
   - All OpenCode coding commands stripped out
   - `.scriptName("argus")` set
   - When run with no args → shows Argus logo + command help
   - When run with args → dispatches to the appropriate command

2. **Created `src/argus/logo.ts` — Argus ASCII art**
   - Custom glyphs for the "ARGUS" wordmark in the terminal UI

3. **Created `src/argus/ui.ts` — Argus branded UI utilities**
   - Reuses all formatting infrastructure from OpenCode UI
   - Argus wordmark and color scheme
   - `logo()`, `error()`, `println()` functions with Argus branding

4. **Updated `bin/argus`** — points to `src/argus/index.ts`

5. **Created `src/argus/tui-commands.ts` — Argus slash commands**
   - `/assess` — runs full assessment against a target
   - `/doctor` — runs health checks
   - `/recon` — runs deterministic recon against a target
   - `/status` — shows system status (MCP worker, tools, database)
   - `/findings` — browses findings from latest engagement
   - `/engagements` — lists all saved engagements
   - `/tools` — shows registered MCP tools and capabilities
   - `/workflows` — shows loaded workflow definitions
   - `/config` — shows effective configuration

**Verification:**
```
$ argus
→ Shows Argus logo + command help ✓

$ argus doctor
→ Runs health check ✓

$ argus --help
→ Shows only Argus commands (no coding commands) ✓
```

---

### Phase 2: Argus TUI Routes (3-5 days)

**Objective:** Build assessment-centric routes that replace the chat-based Home/Session pattern.

**Plan:**

1. **Create `src/argus/tui/routes/` directory**

   Copy the existing TUI infrastructure from `src/cli/cmd/tui/` but provide new routes:

   ```
   src/argus/tui/
   ├── app.tsx            ← Modified from src/cli/cmd/tui/app.tsx
   ├── routes/
   │   ├── dashboard.tsx  ← Scan history, quick actions
   │   ├── scan.tsx       ← Live scan view (replaces session.tsx)
   │   ├── findings.tsx   ← Findings browser
   │   ├── report.tsx     ← Report viewer
   │   ├── settings.tsx   ← Configuration
   │   └── terminal.tsx   ← Raw CLI access
   ├── component/          ← Reused from @tui/component/
   └── context/            ← Reused from @tui/context/
   ```

2. **Dashboard route** (`/dashboard`)
   - Shows recent engagements list (from `EngagementStore`)
   - "New Scan" button → prompts for target URL
   - Quick actions: Doctor, Last Report, Open Config
   - Status indicators: MCP worker health, tool count, recent findings
   - Uses existing TUI component patterns (`useSync`, render loop, keybindings)

3. **Scan route** (`/scan`)
   - Replaces the `Session` route's role as the main interactive view
   - Shows real-time scan progress (phase-by-phase as the executor runs)
   - Phase timeline sidebar (replacing chat sidebar)
   - Findings stream as they're discovered
   - Uses the existing `render` loop, `keymap`, and `footer` patterns
   - Reuses the permission dialog (`dialog-retry-action.tsx`) for approval gates

4. **Findings route** (`/findings`)
   - Table/list view of all findings from the current or selected engagement
   - Filter by severity, confidence, tool, phase
   - Detail view: evidence, HTTP requests/responses, screenshots
   - Confidence promotion visualization

5. **Report route** (`/report`)
   - Renders `ReportGenerator.generateMarkdown()` output in a scrollable view
   - Export buttons: Markdown, JSON, SARIF, HTML
   - Print-friendly formatting

6. **Settings route** (`/settings`)
   - LLM provider configuration (reuses existing provider UI)
   - Tool paths and credentials
   - Feature flags toggles

7. **Terminal route** (`/terminal`)
   - Embedded readline/REPL for running raw `argus <cmd>` commands inside the TUI
   - Uses existing `pty/` infrastructure

**Key reuse strategy:**
- All `@tui/context/*` providers are reused as-is (project, theme, event, sdk, sync, route, exit, kv, args, local, editor, prompt)
- All `@tui/component/dialog-*` are reused (dialog-model, dialog-mcp, dialog-status, dialog-session-list, etc.)
- The `keymap.tsx` is reused with new bindings for Argus actions
- The `footer.tsx` from session route is adapted for scan status
- The `ToastProvider`, `DialogProvider`, `ErrorBoundary` are reused exactly

---

### Phase 3: Replace Chat Model with Scan Model (2-3 days)

**Objective:** The main interactive flow becomes "configure scan → run scan → view findings" instead of "type prompt → get LLM reply."

**Plan:**

1. **Create `src/argus/tui/models/scan-model.ts`**
   - State machine:
     ```
     IDLE → CONFIGURING → SCANNING → REVIEWING → REPORTING → DONE
     ```
   - Holds: target, selected workflow, current phase, findings accumulator, errors
   - Emits events that the TUI subscribes to (phase change, finding discovered, error)

2. **Replace `src/session/` with `src/argus/tui/models/` for the TUI layer**
   - Don't delete `src/session/` — OpenCode's session system is still used internally by the provider/LLM layer
   - The TUI layer just stops presenting a chat interface

3. **Wire the executor into the scan model**
   - `InProcessExecutor.execute(phase)` runs inside the scan model's state machine
   - Each phase completion updates the TUI via SolidJS reactivity
   - Approval gates trigger the existing `DialogProvider` for user confirmation

4. **Prompt input repurposed**
   - The existing `<Prompt>` component becomes a **target URL input** + **workflow selector**
   - Autocomplete from recent targets (stored in EngagementStore)
   - Workflow selection: Quick Scan, Full Assessment, API Assessment, Browser Assessment

---

### Phase 4: Asset Library & Evidence Browser (2-3 days)

**Objective:** Make findings, evidence, and artifacts first-class visual citizens in the TUI.

**Plan:**

1. **Create `src/argus/tui/routes/asset-viewer.tsx`**
   - Screenshot gallery from browser verifiers (uses existing `EvidencePackage`/`ArtifactRef` types)
   - HTTP request/response viewer (syntax highlighted)
   - HAR file viewer
   - Network timeline visualization

2. **Create `src/argus/tui/component/finding-card.tsx`**
   - Severity badge (color-coded: INFO, LOW, MEDIUM, HIGH, CRITICAL)
   - Confidence indicator (INFORMATIONAL → CONFIRMED)
   - CVE/CWE/OWASP references
   - Evidence thumbnails
   - Promotion/demotion actions

3. **Adapt existing dialog components**
   - `dialog-session-list.tsx` → `dialog-engagement-list.tsx`
   - `dialog-workspace-list.tsx` → `dialog-target-list.tsx`
   - `dialog-model.tsx` → `dialog-workflow-selector.tsx`

---

### Phase 5: OpenCode Runtime Internalization (1-2 days)

**Objective:** Remove all "OpenCode" branding from the user experience while keeping the runtime intact.

**Plan:**

1. **Audit all user-facing strings**
   - `src/cli/ui.ts` — update `logo()` to render "Argus" wordmark
   - `src/cli/cmd/tui/app.tsx` — terminal title from `"OC | ..."` to `"Argus | ..."`
   - `src/cli/cmd/tui/keymap.tsx` — update help text references
   - `src/cli/cmd/tui/routes/home.tsx` — placeholder prompts become scan suggestions
   - `src/cli/logo.ts` — replace ASCII art

2. **Environment variables**
   - Keep `process.env.OPENCODE_*` as internal runtime config
   - Add `process.env.ARGUS_*` for user-facing config
   - Both resolve to the same underlying values

3. **Package/namespace strategy**
   - Don't rename `@opencode-ai/*` packages — they're internal dependencies
   - Don't move files out of `src/cli/` — just select which routes/commands are exposed
   - The `src/argus/` directory becomes the user-facing layer; `src/cli/` and `src/session/` are internal

---

### Phase 6: Remove Coding-Assistant Commands (1 day)

**Objective:** Ship a clean Argus binary that doesn't expose coding commands.

**Plan:**

1. **`src/argus/index.ts` command whitelist:**
   ```
   Keep:    assess, doctor, report, resume, verify, evidence, config
   Remove:  run, generate, account, providers, agent, upgrade, uninstall,
            serve, debug, stats, mcp, github, export, import, pr, session,
            db, web, models, plugin, tui/thread, tui/attach
   Keep:    acp (protocol support)
   Keep:    completion, help, version (standard CLI)
   ```

2. **Remove `src/cli/cmd/run/` infrastructure from the Argus entry**
   - The `run` command is the coding-assistant prompt loop
   - The `src/cli/cmd/run/` directory stays for OpenCode but isn't imported by `src/argus/index.ts`

3. **Keep `src/cli/cmd/tui/` intact** — the TUI rendering infrastructure is shared
   - The TUI is now launched by `src/argus/tui/app.tsx` instead of `src/cli/cmd/tui/app.tsx`
   - Or better: `src/argus/tui/app.tsx` re-exports most of `src/cli/cmd/tui/app.tsx` but overrides routes

---

## File Map: Current → Target

| Current Location | Target Location | Action |
|---|---|---|
| `src/index.ts` (OpenCode CLI+Argus) | `src/index.ts` (OpenCode only) | Keep for OpenCode devs |
| `src/argus/main.ts` (Argus CLI) | `src/argus/main.ts` | Keep (CLI mode) |
| — | `src/argus/index.ts` | **New**: Argus TUI entry point |
| `bin/argus` | `bin/argus` | Point to `src/argus/index.ts` |
| `src/cli/cmd/tui/app.tsx` | `src/argus/tui/app.tsx` | **New**: Argus version with own routes |
| `src/cli/cmd/tui/routes/` | `src/argus/tui/routes/` | **New**: dashboard, scan, findings, report, settings, terminal |
| `src/cli/cmd/tui/component/` | `@tui/component/` (imported by argus) | Reuse as-is |
| `src/cli/cmd/tui/context/` | `@tui/context/` (imported by argus) | Reuse as-is |
| `src/cli/cmd/tui/ui/` | `@tui/ui/` (imported by argus) | Reuse as-is |
| `src/cli/cmd/tui/keymap.tsx` | `@tui/keymap` (imported by argus) | Reuse with Argus bindings |
| `src/cli/` | `src/cli/` | Keep as internal OpenCode runtime |
| `src/session/` | `src/session/` | Keep as internal runtime |
| `src/provider/` | `src/provider/` | Keep as internal runtime |
| `src/argus/commands/` | `src/argus/commands/` | Keep (already good) |
| `src/argus/planner/` | `src/argus/planner/` | Keep (already good) |
| `src/argus/bridge/` | `src/argus/bridge/` | Keep (already good) |
| `src/argus/engagement/` | `src/argus/engagement/` | Keep (already good) |
| `src/argus/workflows/` | `src/argus/workflows/` | Keep (already good) |

## Key Technical Decisions

| Decision | Rationale |
|---|---|
| **Don't fork `@opencode-ai/*` packages** | They're internal runtime. Renaming them creates maintenance burden with zero user-facing benefit. |
| **New `src/argus/tui/` directory, not modify `src/cli/cmd/tui/` in place** | Keeps OpenCode development possible. Two UIs can coexist from one checkout. |
| **`src/argus/tui/app.tsx` reuses `@tui/*` imports** | Every `@tui/` import is resolved by `tsconfig.json` paths to `src/cli/cmd/tui/`. The Argus TUI gets all infrastructure for free. |
| **Scan model replaces session model at TUI layer only** | The `src/session/` module continues to function for LLM interactions. The TUI just stops rendering the chat interface. |
| **Don't delete OpenCode commands, just don't import them** | The OpenCode entry (`src/index.ts`) stays functional for development. The Argus entry (`src/argus/index.ts`) only imports whitelisted commands. |

## What Success Looks Like

```
$ argus
╔══════════════════════════════════════════════════╗
║              ARGUS Security Platform             ║
╠══════════════════════════════════════════════════╣
║  Recent Engagements:                             ║
║  ┌────────────────────────────────────────────┐  ║
║  │ example.com  │ 18 findings │ 2026-06-04   │  ║
║  │ juice-shop   │ 42 findings │ 2026-06-03   │  ║
║  │ dvwa         │ 12 findings │ 2026-06-02   │  ║
║  └────────────────────────────────────────────┘  ║
║                                                  ║
║  [New Scan]  [Doctor]  [Reports]  [Settings]     ║
║                                                  ║
║  Status: MCP Worker ✓  |  45 tools registered    ║
╚══════════════════════════════════════════════════╝

$ argus scan https://example.com
→ Opens interactive TUI with live scan progress
→ Shows findings as they're discovered
→ Opens report when complete

$ argus doctor
→ Existing health check (no change)
```

The user never types a coding prompt. They type `argus`, see a security dashboard, and launch scans.

## Open Items

1. **Should `bun dev` launch the Argus TUI or the OpenCode TUI?**
   - Recommendation: `bun dev` = Argus TUI (since this is the product). OpenCode devs use `bun run src/index.ts`
   
2. **Should we keep the `run` command for ad-hoc LLM queries?**
   - Recommendation: No. Argus is a security tool, not a chatbot. Users who want an LLM should use OpenCode separately.

3. **How deep should the `@opencode-ai/` renaming go?**
   - Recommendation: Not at all. These are implementation packages. The user never sees package names.
