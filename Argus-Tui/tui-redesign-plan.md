# TUI Redesign Plan — Complete UI Component Map

## Architecture Overview

- **Framework**: Solid.js + OpenTUI (custom terminal UI rendering engine)
- **Renderer**: `@opentui/core` → `CliRenderer` — draws `box`, `text`, `scrollbox`, `input`, `textarea`, `markdown`, `code`, `diff`, `spinner`, `line_number` JSX elements
- **State**: Solid.js stores (`createStore`, `reconcile`) + Context-based providers (22 contexts)
- **Routing**: Custom context-based (`context/route.tsx`) — no router library. Just `<Switch>/<Match>` on `route.data.type`
- **Keymap**: `@opentui/keymap` — mode-based keybinding system with leader key (`ctrl+x`)

---

## 1. Provider Tree (app.tsx:237-298)

All 22 context providers wrapping the `<App>` component. Order matters for dependency chains.

```
ErrorBoundary
  OpencodeKeymapProvider   — keymap/keybind system
    ArgsProvider           — CLI args (model, agent, prompt, sessionID, etc.)
      ExitProvider         — exit lifecycle
        KVProvider         — file-backed key-value store (UI prefs, animations, etc.)
          ToastProvider    — notification toast system
            RouteProvider  — navigation state (current route)
              TuiConfigProvider — resolved TuiConfig
                SDKProvider — API client, SSE event bus
                  ProjectProvider — workspace/instance management
                    SyncProvider — central state store
                      SyncProviderV2
                        ThemeProvider — theme resolution (33 themes + custom)
                          LocalProvider — local persisted state
                            PromptStashProvider
                              DialogProvider — modal dialog stack
                                FrecencyProvider
                                  PromptHistoryProvider
                                    PromptRefProvider
                                      EditorContextProvider
                                        App (main UI)
```

**Redesign notes**: Each provider is an independent wrapper. To restyle, you only need to modify rendering components. Provider logic stays.

---

## 2. Root App Component (app.tsx:1092-1157)

The root layout box fills terminal dimensions.

```
box (width=dimensions.width, height=dimensions.height, bg=theme.background)
  ├─ [TTFD debug] (conditional)
  ├─ [Content] (flexGrow=1) — shown when `ready()`
  │   └─ Switch/Match — route dispatcher:
  │       ├── "dashboard" → <ArgusDashboard />
  │       ├── "home"      → <Home />
  │       ├── "session"   → <Session /> (keyed by sessionID)
  │       ├── "scan"      → <ScanDashboard />
  │       ├── "findings"  → <FindingsViewer />
  │       ├── "finding"   → <FindingDetail />
  │       ├── "engagement"→ <EngagementDetail />
  │       ├── "engagements"→ <EngagementBrowser />
  │       ├── "workspace" → <Workspace />
  │       └── "plugin"    → plugin route (dynamic)
  ├─ [Plugin Slot "app_bottom"] (flexShrink=0)
  ├─ [Plugin Slot "app"] (flexShrink=0)
  └─ <StartupLoading /> (shown until ready)
```

**Hardcoded values for redesign**:
- `width={dimensions().width}`, `height={dimensions().height}` (line 1094-1095)
- `backgroundColor={theme.background}` (line 1097)
- Mouse event handlers (lines 1098-1106)
- Terminal title strings: `"Argus"`, `"Argus | ${title}"` (lines 488-505)

---

## 3. Route Definitions (context/route.tsx)

| Route Type | Fields | Rendered Component | File |
|---|---|---|---|
| `home` | `prompt?` | `<Home />` | `routes/home.tsx` |
| `session` | `sessionID`, `prompt?` | `<Session />` | `routes/session/index.tsx` |
| `plugin` | `id`, `data?` | Dynamic plugin render | `app.tsx:1084-1090` |
| `scan` | `target`, `engagementId` | `<ScanDashboard />` | `argus/tui/routes/scan.tsx` |
| `findings` | `engagementId?` | `<FindingsViewer />` | `argus/tui/routes/findings.tsx` |
| `finding` | `findingId` | `<FindingDetail />` | `argus/tui/routes/finding-detail.tsx` |
| `dashboard` | — | `<ArgusDashboard />` | `argus/tui/routes/dashboard.tsx` |
| `engagements` | — | `<EngagementBrowser />` | `argus/tui/routes/engagements.tsx` |
| `engagement-detail` | `engagementId`, `tab?` | `<EngagementDetail />` | `argus/tui/routes/engagement-detail.tsx` |
| `workspace` | — | `<Workspace />` | `argus/tui/routes/workspace.tsx` |
| `report` | `engagementId` | (not matched in Switch) | `argus/tui/routes/...` |

**Navigation API**: `route.navigate(route)` — replaces current route via `reconcile()`

---

## 4. Home Route (routes/home.tsx) — 175 lines

```
box (flexGrow=1, flexDirection="column", paddingLeft=2, paddingRight=2)
  ├─ box (alignItems="center", paddingTop=2)
  │   └─ <Logo shape={argusLogo} idle />          ← component/logo.tsx (885 lines, complex animation)
  ├─ box (alignItems="center", paddingTop=1)
  │   └─ text "Autonomous Security Assessment Platform"  ← STATIC STRING
  ├─ box (alignItems="center", paddingTop=1)
  │   └─ text "● Ready for assessment operations."       ← STATIC STRING
  ├─ [Summary Stats] (conditional on stats())
  │   └─ box row with gap=3:
  │       ├─ box column: text (bold) → stats().targets / "targets"
  │       ├─ box column: text (bold, warning) → stats().active / "active"
  │       └─ box column: text (bold, error) → stats().findings / "findings"
  ├─ box (height=1) — spacer
  ├─ box row (maxWidth=promptMaxWidth)
  │   ├─ box column (flexGrow=1)
  │   │   ├─ "Quick Actions"                          ← STATIC STRING
  │   │   ├─ "/assess <target>"                       ← STATIC STRING
  │   │   ├─ "/recon  <target>"                       ← STATIC STRING
  │   │   ├─ "/report <id>"                           ← STATIC STRING
  │   │   ├─ "/doctor"                                ← STATIC STRING
  │   │   └─ "/status"                                ← STATIC STRING
  │   └─ box column (flexGrow=1)
  │       ├─ "Recent Engagements"                     ← STATIC STRING
  │       ├─ [For engagements] each with target + status
  │       ├─ spacer
  │       ├─ "System"                                 ← STATIC STRING
  │       ├─ "● MCP Worker"                           ← STATIC STRING
  │       ├─ "● Planner"                              ← STATIC STRING
  │       ├─ "● Evidence Store"                       ← STATIC STRING
  │       └─ statusLine() text
  ├─ box (paddingTop=2, width="100%", maxWidth=promptMaxWidth)
  │   └─ [Plugin Slot "home_prompt"] → <Prompt ref={bind} />  ← component/prompt/index.tsx
  ├─ box (flexGrow=1, minHeight=0) — spacer
  └─ <Toast />
box (width="100%", flexShrink=0)
  └─ [Plugin Slot "home_footer"]
```

**Replaceable elements**:
- Logo component (`component/logo.tsx`) — 885-line complex animated SVG-like terminal art
- All label strings
- Stats block layout/colors
- Quick actions list layout
- Recent engagements list
- System status indicators
- Prompt component instance

---

## 5. Session Route (routes/session/index.tsx) — 2520 lines

The most complex route. Layout:

```
box (flexGrow=1, flexDirection="column")
  ├─ <PathFormatterProvider>
  │   └─ box row (flexGrow=1, minHeight=0)
  │       ├─ box column (flexGrow=1)
  │       │   ├─ scrollbox (message list, flexGrow=1)
  │       │   │   └─ For each message:
  │       │   │       ├─ UserMessage
  │       │   │       │   ├─ text (markdown rendering)
  │       │   │       │   └─ [File badges]
  │       │   │       ├─ AssistantMessage
  │       │   │       │   ├─ TextPart (markdown)
  │       │   │       │   ├─ ReasoningPart (thinking/thought block)
  │       │   │       │   └─ ToolPart (dispatched by tool type)
  │       │   │       │       ├─ Shell tool
  │       │   │       │       │   ├─ Collapsible block
  │       │   │       │       │   ├─ Command header with icon
  │       │   │       │       │   ├─ Output (max 10 lines truncated)
  │       │   │       │       │   └─ Exit code display
  │       │   │       │       ├─ Write tool
  │       │   │       │       │   ├─ File path header
  │       │   │       │       │   └─ Diff view
  │       │   │       │       ├─ Edit tool
  │       │   │       │       │   ├─ Search/replace diff
  │       │   │       │       │   └─ File path header
  │       │   │       │       ├─ Glob tool
  │       │   │       │       ├─ Grep tool
  │       │   │       │       ├─ Read tool
  │       │   │       │       ├─ WebFetch tool
  │       │   │       │       ├─ WebSearch tool
  │       │   │       │       ├─ ApplyPatch tool
  │       │   │       │       ├─ Task tool (subagent)
  │       │   │       │       ├─ Question tool
  │       │   │       │       ├─ Skill tool
  │       │   │       │       ├─ TodoWrite tool
  │       │   │       │       └─ GenericTool (fallback)
  │       │   │       └─ [Message actions] (copy, retry, etc.)
  │       │   ├─ [PermissionPrompt] (conditional)
  │       │   ├─ [QuestionPrompt] (conditional)
  │       │   ├─ [SubagentFooter] (conditional)
  │       │   ├─ [Prompt] (textarea input with autocomplete)
  │       │   │   └─ [Plugin Slot "prompt_left"]
  │       │   │   └─ [Plugin Slot "prompt_right"]
  │       │   └─ <Toast />
  │       └─ [Sidebar] (width=42, conditional on kv setting)
  └─ <Footer />
```

**Hardcoded values**:
- `INLINE_TOOL_ICON_WIDTH = 2` (icon character width)
- `GO_UPSELL_WINDOW = 86_400_000` (24h)
- `contentWidth = dimensions - sidebar(42) - 4`
- Shell output maxLines = 10, text maxLines = 3
- Scroll acceleration, animation toggles via KV

**Tool part icons** (replaceable): Each tool has an icon character, header style, and collapsible layout. Tool parts are switch-matched by type string.

### 5a. Session Sidebar (sidebar.tsx) — 102 lines

```
box (bg=theme.backgroundPanel, width=42, height="100%", padding)
  └─ scrollbox (flexGrow=1)
      └─ box (flexShrink=0, gap=1)
          ├─ [Plugin Slot "sidebar_title"] (single_winner)
          │   └─ Default: title (bold), sessionID, workspace label, share URL
          └─ [Plugin Slot "sidebar_content"]
  box (flexShrink=0)
    └─ [Plugin Slot "sidebar_footer"] (single_winner)
        └─ Default: "● OpenCode v{version}"
```

**Replaceable**: Sidebar width (42), colors, layout, branding "OpenCode" text, title/session ID formatting

### 5b. Session Footer (footer.tsx) — 91 lines

```
box row (justifyContent="space-between", gap=1, flexShrink=0)
  ├─ text directory path (left-aligned)
  └─ box row (right-aligned, gap=2)
      ├─ [Welcome message] /connect
      ├─ [Permissions count] "△ N Permission(s)"
      ├─ [LSP count] "• N LSP"
      ├─ [MCP count] "⊙ N MCP"
      └─ "/status"
```

**Replaceable**: All footer indicators, welcome messages, spacing

---

## 6. Argus Routes (packages/opencode/src/argus/tui/routes/)

### 6a. ArgusDashboard (dashboard.tsx) — 128 lines

Main landing page replacing home. Shows metrics and recent engagements.

```
box (flexGrow=1, flexDirection="column", padding)
  ├─ box (header with "Argus Security Platform" + subtitle)
  ├─ [Stats row] (total targets, open engagements, confirmed findings)
  ├─ Recent engagements table/list
  ├─ Quick action buttons
  └─ Status bar
```

### 6b. ScanDashboard (scan.tsx)

Scan target input + progress view. Shows scan status, findings.

### 6c. FindingsViewer (findings.tsx)

Filterable/sortable list of findings with severity badges, status, target.

### 6d. FindingDetail (finding-detail.tsx)

Full finding detail view with description, evidence, remediation.

### 6e. EngagementBrowser (engagements.tsx)

List of engagements with filters, search, status indicators.

### 6f. EngagementDetail (engagement-detail.tsx)

Full engagement view with tabs (overview, findings, timeline, evidence).

### 6g. Workspace (workspace.tsx)

Workspace management page.

### 6h. EvidenceViewer (evidence-viewer.tsx)

Evidence file viewer.

---

## 7. Dialog Layer (ui/dialog.tsx + 30+ dialog components)

**Dialog container** (ui/dialog.tsx):
```
box (absolute, zIndex=3000, full terminal size, dimmed bg)
  └─ box (centered, width=60/88/116, maxWidth=terminal-2, bg=theme.backgroundPanel, paddingTop=1)
      └─ [Dialog content]
```

Sizes: `medium`=60, `large`=88, `xlarge`=116

**Dialog types**:

| Dialog Component | File | Purpose |
|---|---|---|
| `Dialog` (container) | `ui/dialog.tsx` | Modal wrapper with backdrop, z-index, stack management |
| `DialogSelect` | `ui/dialog-select.tsx` | Generic searchable/filterable select list (579 lines) |
| `DialogAlert` | `ui/dialog-alert.tsx` | Alert with OK button |
| `DialogConfirm` | `ui/dialog-confirm.tsx` | Yes/no confirm dialog |
| `DialogPrompt` | `ui/dialog-prompt.tsx` | Text input prompt |
| `DialogHelp` | `ui/dialog-help.tsx` | Keybindings help |
| `DialogExportOptions` | `ui/dialog-export-options.tsx` | Export session |
| `DialogModel` | `component/dialog-model.tsx` | Model selection |
| `DialogAgent` | `component/dialog-agent.tsx` | Agent selection |
| `DialogProvider` | `component/dialog-provider.tsx` | Provider list |
| `DialogMcp` | `component/dialog-mcp.tsx` | MCP server toggles |
| `DialogVariant` | `component/dialog-variant.tsx` | Model variant selection |
| `DialogThemeList` | `component/dialog-theme-list.tsx` | Theme switcher |
| `DialogSessionList` | `component/dialog-session-list.tsx` | Session list/switcher |
| `DialogSessionRename` | `component/dialog-session-rename.tsx` | Rename session |
| `DialogSessionDeleteFailed` | `component/dialog-session-delete-failed.tsx` | Delete error |
| `DialogStash` | `component/dialog-stash.tsx` | Prompt stash |
| `DialogSkill` | `component/dialog-skill.tsx` | Skill selector |
| `DialogStatus` | `component/dialog-status.tsx` | System status |
| `DialogTag` | `component/dialog-tag.tsx` | Tag management |
| `DialogConsoleOrg` | `component/dialog-console-org.tsx` | Org switcher |
| `DialogRetryAction` | `component/dialog-retry-action.tsx` | Retry action |
| `DialogWorkspaceList` | `component/dialog-workspace-list.tsx` | Workspace list |
| `DialogWorkspaceCreate` | `component/dialog-workspace-create.tsx` | Create workspace |
| `DialogWorkspaceFileChanges` | `component/dialog-workspace-file-changes.tsx` | File changes |
| `DialogWorkspaceUnavailable` | `component/dialog-workspace-unavailable.tsx` | Unavailable |
| `CommandPaletteDialog` | `component/command-palette.tsx` | Command palette |
| `DialogMessage` | `routes/session/dialog-message.tsx` | Message detail |
| `DialogTimeline` | `routes/session/dialog-timeline.tsx` | Session timeline |
| `DialogForkFromTimeline` | `routes/session/dialog-fork-from-timeline.tsx` | Fork from timeline |
| `DialogSubagent` | `routes/session/dialog-subagent.tsx` | Subagent info |

**Dialog API**: `dialog.show(element)`, `dialog.replace(element)`, `dialog.clear()`, `dialog.back()` — stack-based, pushes "modal" keymap mode

---

## 8. Prompt System (component/prompt/)

| File | Purpose |
|---|---|
| `index.tsx` | Main Prompt component — textarea with autocomplete overlay, context chip display, stash button, history handler, submit |
| `autocomplete.tsx` | Dropdown autocomplete popup during input |
| `cwd.ts` | Current working directory display in prompt |
| `frecency.tsx` | Frecency-based history sorting |
| `history.tsx` | Prompt history navigation (up/down arrows) |
| `stash.tsx` | Stash provider — save/recall prompt templates |
| `part.ts` | Prompt part types (file references, context) |
| `traits.ts` | Prompt trait helpers |

**Replaceable**: Input styling, autocomplete popup appearance, context chip rendering, placeholder text, layout

---

## 9. Reusable UI Components

| Component | File | Description |
|---|---|---|
| `Logo` | `component/logo.tsx` | 885-line animated terminal logo (shimmer, ring waves, burst on press, idle animation) |
| `Spinner` | `component/spinner.tsx` | Animated spinner, uses `opentui-spinner`, toggleable via KV |
| `Border` | `component/border.tsx` | EmptyBorder, SplitBorder constants |
| `StartupLoading` | `component/startup-loading.tsx` | Full-screen loading indicator |
| `ErrorComponent` | `component/error-component.tsx` | Error boundary UI with reset/exit |
| `PluginRouteMissing` | `component/plugin-route-missing.tsx` | Fallback when plugin route not found |
| `UseConnected` | `component/use-connected.tsx` | Connection status hook/indicator |
| `WorkspaceLabel` | `component/workspace-label.tsx` | Workspace type + status badge |
| `BgPulse` | `component/bg-pulse.tsx` | Background pulse animation |
| `BgPulseRender` | `component/bg-pulse-render.ts` | Pulse render utilities |
| `TodoItem` | `component/todo-item.tsx` | Todo list item rendering |
| `CommandPalette` | `component/command-palette.tsx` | Command palette dialog |
| `Toast` | `ui/toast.tsx` | Notification toast (top-right, auto-dismiss, info/success/warning/error) |
| `Link` | `ui/link.tsx` | Clickable link |
| `Spinner` (util) | `ui/spinner.ts` | Knight Rider scanner animation creator |
| `PermissionPrompt` | `routes/session/permission.tsx` | Permission approval dialog inline |
| `QuestionPrompt` | `routes/session/question.tsx` | Question prompt inline |
| `SubagentFooter` | `routes/session/subagent-footer.tsx` | Subagent session bar |

---

## 10. Theme System (context/theme.tsx) — 1251 lines

**Theme structure** (per `ThemeJson`):
- 40+ color slots: `primary`, `secondary`, `accent`, `error`, `warning`, `success`, `info`, `text`, `textMuted`, `background`, `backgroundPanel`, `backgroundElement`, `backgroundMenu`, `border`, `borderActive`, `borderSubtle`, `diffAdded`/`diffRemoved`/`diffContext`/diff header colors, `markdown*` colors (12), `syntax*` colors (9), `thinkingOpacity`, `selectedListItemText`
- 33 bundled JSON themes in `context/theme/*.json`
- Custom themes from `~/.config/opencode/themes/` and `.opencode/themes/`
- `system` theme auto-generated from terminal palette
- Syntax highlighting: `generateSyntax()` + `generateSubtleSyntax()` → ~80 scope rules in `SyntaxStyle`
- Dark/light mode detection + lock

**Replaceable**: All theme color values, syntax highlight rules, markdown rendering colors, diff colors

---

## 11. Keybinding System (keymap.tsx + config/keybind.ts)

- Mode stack: `base`, `modal`, custom modes
- ~230 keybinding definitions in `config/keybind.ts`
- Leader key: `ctrl+x` (default)
- Commands registered via `registerOpencodeKeymap()` with categories
- Input commands for textarea layers
- Plugin-accessible via `keymap.registerCommand()`, `keymap.dispatchCommand()`

**Replaceable**: Keybind definitions, mode names, leader key, command names

---

## 12. Plugin System

| File | Purpose |
|---|---|
| `plugin/runtime.ts` | Plugin lifecycle — load/dispose TUI plugins |
| `plugin/api.tsx` | Plugin API surface (dialog, keymap, KV, route, events, theme, toast, renderer, attention) |
| `plugin/slots.tsx` | Named render slots (`home_prompt`, `sidebar_title`, `sidebar_content`, `sidebar_footer`, `app_bottom`, `app`, `prompt_left`, `prompt_right`, `home_footer`) |
| `plugin/internal.ts` | Internal plugin support |
| `plugin/command-shim.ts` | Command compatibility shim |

---

## 13. Hardcoded Strings for Replacement

| Location | String |
|---|---|
| `app.tsx:488` | `"Argus"` — terminal title |
| `app.tsx:495,499` | `"Argus"`, `"Argus | ${title}"` — terminal title |
| `app.tsx:505` | `"Argus | ${route.data.id}"` — plugin terminal title |
| `home.tsx:106` | `"Autonomous Security Assessment Platform"` |
| `home.tsx:109` | `"● Ready for assessment operations."` |
| `home.tsx:131-136` | Quick action labels |
| `sidebar.tsx:91-95` | `"● OpenCode v..."` brand |
| `footer.tsx:59` | `"Get started /connect"` |
| `footer.tsx:85` | `"/status"` |
| Various dialogs | Titles, messages, button labels |

---

## 14. Layout Constants

| Value | Location | Purpose |
|---|---|---|
| `42` | `app.tsx:91`, `sidebar.tsx:29` | Sidebar width (chars) |
| `60, 88, 116` | `app.tsx:22-26`, `dialog.tsx:22-26` | Dialog widths |
| `40` | `app.tsx:499` | Title truncation length |
| `3` | `app.tsx:499` | Ellipsis chars |
| `2` | session/index.tsx:1529 | Inline tool icon width |
| `10` | session/index.tsx:2016 | Shell output max lines |
| `3` | session/index.tsx:1753 | Text max lines |
| `85` | `home.tsx:38` | Default prompt max width |
| `3000` | `dialog.tsx:44` | Dialog z-index |

---

## 15. How to Approach Redesign

**Strategy**: The TUI is modular enough to replace piece by piece. Recommended order:

1. **Theme** — Change `context/theme/opencode.json` colors → instantly updates all components using `useTheme()`. This is the cheapest win.

2. **Logo** — Replace `component/logo.tsx` with simpler/shorter version or remove animation.

3. **Home page** — Redesign `routes/home.tsx`. Replace logo, stats, quick actions, system status sections.

4. **Dialog styling** — Modify `ui/dialog.tsx` for backdrop color, sizing, border style; then `ui/dialog-select.tsx` for list item styling.

5. **Session messages** — Modify tool part rendering in `routes/session/index.tsx`. Each tool has a `<Match when={...}>` branch you can restyle independently.

6. **Sidebar** — Modify `sidebar.tsx` width, layout, colors, branding text.

7. **Footer** — Modify `footer.tsx` indicators and layout.

8. **Prompt** — Modify `component/prompt/index.tsx` textarea styling, autocomplete popup, context chips.

9. **Toast** — Modify `ui/toast.tsx` positioning, colors, animation.

10. **Argus routes** — Redesign each individually. They are self-contained Solid.js components.
