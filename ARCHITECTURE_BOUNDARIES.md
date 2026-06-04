# Architecture Boundaries

## Purpose

Argus is a controlled-divergence fork of OpenCode. This document defines the strict import boundary between Argus-specific modules and OpenCode internals to prevent architectural erosion.

## The Rule

Argus modules (`src/argus/`) may depend only on symbols exported from designated public runtime entry points. Direct imports into OpenCode implementation files or subdirectories are prohibited — regardless of directory location or naming convention.

```typescript
// ✅ ALLOWED — public runtime contracts only
import { IProviderManager, ISessionStore, IRuntimeEvents, ICommandRegistry }
  from "@opencode/runtime";

// ❌ PROHIBITED — bypasses public API, couples to file layout
import { Provider } from "../../opencode/providers/provider";
import { SessionManager } from "../../opencode/sessions/manager";
import { KeyBindings } from "../../opencode/tui/keybindings";
```

## Public API Surface

The following entry points are considered stable public contracts that Argus modules may import from:

| Export | Source | Purpose |
|--------|--------|---------|
| `IProviderManager` | `@opencode/runtime` | LLM provider management |
| `ISessionStore` | `@opencode/runtime` | Session persistence |
| `IRuntimeEvents` | `@opencode/runtime` | Event system |
| `ICommandRegistry` | `@opencode/runtime` | Command registration |

## Enforcement

### TypeScript (tsconfig paths)
Argus modules import from `@argus/` prefix which maps to `src/argus/`. Any attempt to import from `../../opencode/` will be caught during code review and CI.

### ESLint (if configured)
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

### Code Review
Every PR touching `src/argus/` must not introduce new direct imports into OpenCode internals.

## Rationale

This boundary enforcement (Option 2 from the V5 design doc — export-boundary enforcement) ensures:

1. **Decoupling**: When OpenCode refactors internals, Argus modules continue to compile unchanged because they depend only on the stable runtime interface surface.
2. **Testability**: Public API surfaces can be mocked/ stubbed independently of internal implementations.
3. **Maintainability**: New team members understand immediately what is public contract vs internal implementation.
4. **Upgrade safety**: Cherry-picking upstream OpenCode changes never breaks Argus modules.

## Exception Process

To add a new import from an OpenCode internal into Argus code:
1. The symbol must be re-exported through the `@opencode/runtime` entry point.
2. A PR adding the export must be reviewed by at least one maintainer.
3. The symbol must have a stable interface (not an implementation detail).

No exceptions for "temporary" direct imports — they become permanent.
