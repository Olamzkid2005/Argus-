# Argus TUI Redesign Prompt

> Use this prompt with the `premium-ui-architect` or `general` agent to redesign the Argus Terminal UI (TUI).

---

## Project Overview

**Argus** is an autonomous security assessment platform. Its primary interface is a **Terminal UI (TUI)** built on a custom framework called **OpenTUI** (`@opentui/*`) with **SolidJS** as the reactive component model. The TUI runs inside a terminal (no browser) using a custom canvas renderer that supports RGBA colors, mouse events, sub-pixel rendering, spinners, animations, and rich text formatting (bold, italic, strikethrough, etc.).

The TUI has two distinct personalities:
1. **OpenCode** — a general-purpose AI coding assistant TUI (chat sessions, diff viewer, file management)
2. **Argus** — a security assessment platform TUI layered on top (dashboard, scan views, findings browser, engagement management)

We want to redesign **the entire TUI frontend** to be visually "better and fancier" — more polished, more visually engaging, with better use of color, typography, spacing, borders, animations, and layout. This is a visual/UX redesign, NOT an architectural rewrite. Keep all existing functionality, data flow, keybindings, and component structure. Make it look **premium**.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Rendering | `@opentui/core` — `CliRenderer`, `BoxRenderable`, `TextareaRenderable`, `ScrollBoxRenderable`, `RGBA` |
| UI Framework | `@opentui/solid` — JSX-to-terminal renderer (`<box>`, `<text>`, `<scrollbox>`, `<span>`, `<textarea>`, `<diff>`, `<spinner>`) |
| Reactive Model | **SolidJS** — signals, stores, effects, memos, contexts |
| Keybinding | `@opentui/keymap` — mode-based keybinding stack |
| Animation | Custom requestAnimationFrame loop, `opentui-spinner`, sub-pixel glow/shimmer effects |

---

## Current Architecture

### Provider/Component Tree (mount order in `app.tsx`)

```
ErrorBoundary
  OpencodeKeymapProvider
    ArgsProvider
      ExitProvider
        KVProvider
          ToastProvider
            RouteProvider
              TuiConfigProvider
                SDKProvider
                  ProjectProvider
                    SyncProvider
                    SyncProviderV2
                      ThemeProvider
                        LocalProvider
                          PromptStashProvider
                          DialogProvider
                            FrecencyProvider
                            PromptHistoryProvider
                            PromptRefProvider
                            EditorContextProvider
                              App
```

### Routes (managed by `RouteProvider`)

| Route Type | Component | Description |
|-----------|-----------|-------------|
| `home` | `Home` | Landing screen with prompt input, quick actions, recent engagements |
| `session` | `Session` | Main chat session — messages, tool outputs, diffs, permission prompts |
| `dashboard` | `ArgusDashboard` | Security assessment dashboard with stats |
| `scan` | `ScanDashboard` | Active scan/assessment view |
| `findings` | `FindingsViewer` | Browse findings for an engagement |
| `finding` | `FindingDetail` | Individual finding detail view |
| `engagements` | `EngagementBrowser` | Browse all engagements |
| `workspace` | `Workspace` | Workspace management |
| `plugin` | Plugin-provided | Dynamically registered routes |

### Core Screens That Need Redesign

#### 1. Home Screen (`routes/home.tsx`)
- Logo display with animated shimmer effect
- Tagline "Autonomous Security Assessment Platform"
- Status line ("Ready for assessment operations.")
- Stats bar (targets, active, findings)
- Quick actions list (commands like `/assess`, `/recon`, etc.)
- Recent engagements list
- System status indicators
- Prompt input at the bottom
- Footer bar at the very bottom

#### 2. Session Screen (`routes/session/index.tsx` — 2520 lines)
- Message list (user messages, assistant messages, tool calls, diffs)
- Thinking/reasoning blocks with fade effect
- Tool output collapsible sections
- Diff viewer (file tree + unified/split diff)
- Permission request overlays
- Question prompts
- Sidebar (42 columns wide) with session info, plugin panels
- Footer with status indicators (MCP, LSP, permissions, directory)
- Toast notifications

#### 3. Session Sidebar (`routes/session/sidebar.tsx`)
- Session title
- Workspace info/label
- Plugin-registered panels (context info, modified files, LSP, MCP, todo list)

#### 4. Session Footer (`routes/session/footer.tsx`)
- Current directory on left
- Status indicators on right: permissions, LSP count, MCP status, `/status` command hint

#### 5. Permission Prompt (`routes/session/permission.tsx` — 719 lines)
- Modal/overlay that shows when a tool needs permission
- Shows the tool type (edit, read, shell, glob, grep, etc.)
- Diff preview for edit permissions
- Option buttons: "Allow once", "Allow always", "Reject"
- Reject sub-prompt with textarea for explanation

#### 6. Dialogs (`ui/dialog.tsx` + 16 dialog components)
- Backdrop overlay with semi-transparent background
- Centered popup with configurable width (60/88/116 cols)
- Dialog types: alert, confirm, prompt, select, help, export
- Specialized dialogs: model/agent/MCP/provider/theme/session/skill/workspace lists

#### 7. Argus Dashboard (`argus/tui/routes/dashboard.tsx`)
- Stats row (total targets, active engagements, confirmed findings)
- Quick actions row
- Recent engagements list with status icons

#### 8. Prompt Input (`component/prompt/index.tsx` — 2011 lines)
- Multi-line textarea with syntax-aware features
- Autocomplete dropdown
- History management
- Stash/queue system
- Frecency scoring for suggestions

#### 9. Startup Loading (`component/startup-loading.tsx`)
- Loading screen shown while providers initialize

#### 10. Feature Plugins (sidebar panels, diff viewer, home footer, which-key, notifications)

---

## Theme System

33 built-in themes in `context/theme/*.json`. Colors defined as hex with dark/light variants.

**Key theme color properties available:**
```
primary, secondary, accent, error, warning, success, info
text, textMuted
background, backgroundPanel, backgroundElement, backgroundMenu
borderSubtle, border, borderActive
diffAdded, diffRemoved, diffContext, diffHunkHeader
diffHighlightAdded, diffHighlightRemoved
diffAddedBg, diffRemovedBg, diffContextBg, diffLineNumber
markdownText, markdownHeading, markdownLink, markdownCode, ...
syntaxComment, syntaxKeyword, syntaxFunction, syntaxVariable, ...
thinkingOpacity
```

**Default theme (OpenCode):**
- Dark: near-black background (#0a0a0a), warm orange primary (#fab283), muted grays
- Light: near-white background, blue primary
- Accent is purple, success is green, error is red, warning is orange

---

## OpenTUI Rendering Primitives Available

These are the JSX elements available for building the UI:

```tsx
// Layout
<box> — flexbox container (flexDirection, alignItems, justifyContent, flexGrow, flexShrink, padding, margin, gap, width, height, minHeight, maxWidth, position, zIndex)
<scrollbox> — scrollable container (verticalScrollbarOptions, scrollAcceleration)
<portal> — render outside normal flow

// Text
<text> — text element (fg, bg, bold, italic, strikethrough, attributes, selectable)
<span> — inline text span (fg, bg, bold, style)
<b> — bold text
<i> — italic text

// Input
<textarea> — multi-line input (textColor, focusedTextColor, cursorColor, focused, traits)
<diff> — diff renderer (diff, view, filetype, syntaxStyle, showLineNumbers, wrapMode, colors)
<spinner> — animated spinner (frames, interval, color)
```

**Layout features:** flexbox model, absolute positioning, z-index stacking, overflow scrolling, mouse events (down/up/drag/over)

---

## What "Better and Fancier" Means Concretely

This is a **terminal UI** — we're limited to text characters, colors, and simple box layouts. But within those constraints, we can achieve a premium look:

### 1. Enhanced Visual Hierarchy
- **Better typographic spacing** — use padding, gaps, and dividers to create clear visual zones
- **Section headers** with subtle styling (underlines, bottom borders, muted backgrounds)
- **Consistent alignment** — everything should feel intentionally placed

### 2. Richer Color Usage
- **Gradient-like effects** using the RGBA color manipulation tools already available (`tint()`, `shade()`, `fade()`)
- **More varied backgrounds** — use `backgroundPanel` (level 2), `backgroundElement` (level 3), `backgroundMenu` to create visual depth
- **Accent color on active elements** — active selection, focused input, hover states
- **Status-aware coloring** — use `success`/`warning`/`error`/`info` consistently across all indicators

### 3. Better Borders & Dividers
- Use border characters (┃, ─, ┌, ┐, └, ┘) to frame panels and sections
- The `SplitBorder` component already defines `┃` for vertical dividers
- Use `border={["left"]}` or `border={["top"]}` on panels for subtle framing
- Create card-like containers with border framing

### 4. Animations & Micro-interactions
- **Smooth transitions** between states (when data loads, when panels appear)
- **Pulsing/glimmer effects** on loading elements (the `Logo` component has sophisticated shimmer code — reuse that pattern)
- **Progressive reveal** of content (fade in stats, results)
- **Subtle breathing** on status indicators (active scan, waiting state)
- The `animations_enabled` KV flag already controls animation toggling — respect it

### 5. Iconography & Symbols
- Use Unicode symbols consistently across the UI:
  - `●` for active/online status
  - `○` for inactive/offline
  - `△` for warnings/permissions
  - `✗` / `✓` for error/success
  - `⟳` for running/in-progress
  - `⊙` for MCP services
  - `→` for actions
  - `›` for breadcrumbs/navigation
  - `◆` for key metrics/emphasized data
  - `▸` / `▾` for collapsible sections
  - `⋮` for "more actions" menus
  - `┃` for vertical panel dividers (already in SplitBorder)
  - `─` for horizontal rules

### 6. Improved Layouts

**Home Screen:**
- Split into logical sections with mini-cards (box containers with borders)
- Stats in a card row with colored numbers and labels
- Quick actions in a nicely formatted grid
- Recent engagements as a scrollable list with status badges
- System status as a compact panel with color-coded health indicators

**Session Screen:**
- Messages should have distinct visual styling: user messages vs assistant messages vs tool calls
- Add subtle left border or background tint to differentiate message types
- Thinking blocks should have a distinct, more faded/ghosted appearance (already partially implemented with `thinkingOpacity`)
- Tool outputs should collapse/expand with smooth transitions
- The sidebar panels should have consistent card-like styling with section labels

**Dialog System:**
- Dialogs should feel like polished modals with a clear backdrop
- Option buttons should have hover/keyboard-navigation highlighting (already exists but could be more polished)
- Dialog headers should have icon + title styling

**Argus Dashboard:**
- Dashboard cards with colored top borders (like kanban cards)
- Stats as large centered numbers with descriptive labels
- Quick action row as styled command chips
- Engagement list with status tags and finding counts

**Footer:**
- Clean two-column layout with directory on left, status on right
- Status indicators should use consistent icon+color patterns
- Should feel lightweight but informative

### 7. Diff Viewer Enhancements
- Already has a file tree, split/unified views, syntax highlighting
- Improve visual distinction between added/removed lines
- Better file tree styling with folder expand/collapse animations
- Line number gutter styling

### 8. Permission Prompt
- Currently functional but visually flat
- Add colored left border matching the severity (warning for permissions)
- Better button/option styling with clearer selection state
- More informative layout with diff preview taking more space

---

## Key Constraints & Rules

1. **Preserve all functionality** — do not break keybindings, data flow, plugin API, or any existing behavior
2. **Work within OpenTUI constraints** — you have `<box>`, `<text>`, `<scrollbox>`, `<textarea>`, `<diff>`, `<spinner>`, `<span>`, `<portal>`, `<b>`, `<i>`
3. **Use the theme system** — never hardcode colors; always reference `theme.xxx` from the theme context
4. **Respect animation preferences** — check `kv.get("animations_enabled", true)` before adding animations; provide static fallback
5. **Responsive layout** — use `useTerminalDimensions()` to adapt to terminal size; handle narrow terminals (<80 columns) gracefully
6. **Accessibility** — maintain clear contrast, support keyboard navigation, keep screen reader compatibility
7. **Performance** — avoid unnecessary re-renders; use `createMemo`, `Show`, `Switch` efficiently; animations should use the existing frame loop pattern (see `logo.tsx` for reference)
8. **Keep the plugin system working** — plugin slots (`sidebar_*`, `home_*`, `session_*`, `app_bottom`, `app`) must remain functional
9. **Don't change file paths** — keep all existing route/component imports working
10. **Consistent styling patterns** — establish a visual pattern and apply it across all screens

---

## Files to Focus On (Primary Redesign Targets)

### Route Screens (visual layout, structure, styling)
- `packages/opencode/src/cli/cmd/tui/routes/home.tsx`
- `packages/opencode/src/cli/cmd/tui/routes/session/index.tsx` (2520 lines — large file)
- `packages/opencode/src/cli/cmd/tui/routes/session/sidebar.tsx`
- `packages/opencode/src/cli/cmd/tui/routes/session/footer.tsx`
- `packages/opencode/src/cli/cmd/tui/routes/session/permission.tsx`
- `packages/opencode/src/cli/cmd/tui/routes/session/question.tsx`
- `packages/opencode/src/cli/cmd/tui/component/startup-loading.tsx`
- `packages/opencode/src/argus/tui/routes/dashboard.tsx`
- `packages/opencode/src/argus/tui/routes/scan.tsx`
- `packages/opencode/src/argus/tui/routes/findings.tsx`
- `packages/opencode/src/argus/tui/routes/finding-detail.tsx`
- `packages/opencode/src/argus/tui/routes/engagements.tsx`
- `packages/opencode/src/argus/tui/routes/engagement-detail.tsx`
- `packages/opencode/src/argus/tui/routes/workspace.tsx`

### Dialog System
- `packages/opencode/src/cli/cmd/tui/ui/dialog.tsx` — base dialog with backdrop
- `packages/opencode/src/cli/cmd/tui/ui/dialog-alert.tsx`
- `packages/opencode/src/cli/cmd/tui/ui/dialog-confirm.tsx`
- `packages/opencode/src/cli/cmd/tui/ui/dialog-prompt.tsx`
- `packages/opencode/src/cli/cmd/tui/ui/dialog-select.tsx`
- `packages/opencode/src/cli/cmd/tui/ui/dialog-help.tsx`
- All `component/dialog-*.tsx` files (model, agent, MCP, theme, session, skill, workspace, variant, stash, tag, retry, console-org, etc.)

### Core Components
- `packages/opencode/src/cli/cmd/tui/component/logo.tsx` — already has advanced shimmer; could be enhanced
- `packages/opencode/src/cli/cmd/tui/component/spinner.tsx` — spinner animations
- `packages/opencode/src/cli/cmd/tui/component/border.tsx` — border character definitions
- `packages/opencode/src/cli/cmd/tui/component/command-palette.tsx`
- `packages/opencode/src/cli/cmd/tui/component/todo-item.tsx`
- `packages/opencode/src/cli/cmd/tui/component/workspace-label.tsx`
- `packages/opencode/src/cli/cmd/tui/component/error-component.tsx`
- `packages/opencode/src/cli/cmd/tui/ui/toast.tsx` — notification toasts

### Feature Plugins
- `packages/opencode/src/cli/cmd/tui/feature-plugins/sidebar/*.tsx` — sidebar panels (context, files, LSP, MCP, todo)
- `packages/opencode/src/cli/cmd/tui/feature-plugins/system/diff-viewer*.tsx`
- `packages/opencode/src/cli/cmd/tui/feature-plugins/system/which-key.tsx`
- `packages/opencode/src/cli/cmd/tui/feature-plugins/home/*.tsx`
- `packages/opencode/src/cli/cmd/tui/feature-plugins/system/notifications.ts`

### App Shell
- `packages/opencode/src/cli/cmd/tui/app.tsx` — the main App component that switches between routes

---

## Getting Oriented

To start, read these key files to understand the current visual state:

1. **Entry & app shell**: `packages/opencode/src/cli/cmd/tui/app.tsx`
2. **Routing & provider hierarchy**: `packages/opencode/src/cli/cmd/tui/context/route.tsx`
3. **Theme system**: `packages/opencode/src/cli/cmd/tui/context/theme.tsx` + `packages/opencode/src/cli/cmd/tui/context/theme/opencode.json`
4. **Default theme**: `packages/opencode/src/cli/cmd/tui/context/theme/opencode.json`
5. **Keybinding system**: `packages/opencode/src/cli/cmd/tui/keymap.tsx`
6. **Home screen**: `packages/opencode/src/cli/cmd/tui/routes/home.tsx`
7. **Session screen**: `packages/opencode/src/cli/cmd/tui/routes/session/index.tsx`
8. **Session sidebar**: `packages/opencode/src/cli/cmd/tui/routes/session/sidebar.tsx`
9. **Permission overlay**: `packages/opencode/src/cli/cmd/tui/routes/session/permission.tsx`
10. **Dialog base**: `packages/opencode/src/cli/cmd/tui/ui/dialog.tsx`
11. **Argus Dashboard**: `packages/opencode/src/argus/tui/routes/dashboard.tsx`
12. **Logo (for animation pattern reference)**: `packages/opencode/src/cli/cmd/tui/component/logo.tsx`
13. **Spinner component**: `packages/opencode/src/cli/cmd/tui/component/spinner.tsx`
14. **Border definitions**: `packages/opencode/src/cli/cmd/tui/component/border.tsx`

---

## Workflow

1. **Plan first** — read the key files, understand the current visual state, then propose a redesign plan
2. **Start with the theme system** — consider if the default theme colors need tweaking for a more premium look
3. **Redesign the app shell** (background, layout container)
4. **Redesign the Home screen** first (it's simpler, good for establishing patterns)
5. **Redesign the Session screen** (the main interface — most important)
6. **Redesign dialogs and overlays**
7. **Redesign the Argus-specific screens**
8. **Polish feature plugins**
9. **Verify** — run `bun typecheck` from `packages/opencode/` to ensure no type errors

---

## Design Principles

- **Terminal-native aesthetic** — don't try to mimic a web UI; lean into what makes terminal UIs beautiful (clean typography, intentional use of color, efficient layouts)
- **Information density with clarity** — this is a professional tool; show a lot of information but organize it clearly
- **Subtle over flashy** — animations and effects should be understated and purposeful (loading states, status transitions, focus indicators)
- **Dark mode first** — since this is a security tool used in terminal environments, optimize for dark mode; ensure light mode still looks good
- **Consistency** — establish one visual language and apply it everywhere (same border style, same spacing, same color semantics)
