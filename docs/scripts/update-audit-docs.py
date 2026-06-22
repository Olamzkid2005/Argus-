"""Update ARCHITECTURE_AUDIT.md and FAILURE_MODE_CHECKLIST.md to reflect cache mode wiring and verbose flag completion."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

# ── ARCHITECTURE_AUDIT.md ──
with open('docs/adr/ARCHITECTURE_AUDIT.md', 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# 1. Summary table - ADR-018 row
old = '| ADR-018 (Cache Mode Semantics) | ⚠️ Partial (improved) | CLI flags partially wired for TUI; executor path still unwired |'
new = '| ADR-018 (Cache Mode Semantics) | ✅ Complete | CLI flags wired for TUI; executor path connected via ExecutionOptions |'
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print('✓ Summary table ADR-018: Partial → Complete')

# 2. ADR-018 claims table - CLI mapping status
old = '| CLI mapping (`--no-cache`, `--refresh-cache`) | ⚠️ Partially implemented | See below |'
new = '| CLI mapping (`--no-cache`, `--refresh-cache`) | ✅ | detectCacheMode() in flag-strip.ts; passes through to executor |'
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print('✓ Claims table CLI mapping: Partially → Complete')

# 3. Discrepancies - replace 'not wired' paragraph
old = """The flags (`--no-cache`, `--refresh-cache`) are now correctly stripped from the URL before creating the engagement or invoking the runner. However, the flags are **still not wired to the executor's `CacheMode` enum** — they are handled purely as string tokens in the TUI prompt interceptor, not as proper `ExecutionOptions` that flow through to `CacheMode.NO_CACHE` / `CacheMode.REFRESH`. The TypeScript `ExecutionOptions` interface in `executor.ts` with `cacheMode` exists but is never connected to a CLI command handler or tool invocation path."""

new = """The flags (`--no-cache`, `--refresh-cache`) are now fully wired through the execution pipeline. `flag-strip.ts` provides `detectCacheMode()` which detects `--no-cache`/`--refresh-cache` flags and returns the corresponding `CacheMode` string. The TUI prompt handler (`prompt/index.tsx`) passes this to `WorkflowRunner.run()` as `cacheMode`. The `WorkflowRunner` forwards it via `executor.setExecutionOptions()` to the `InProcessExecutor`, which passes it through `bridge.callTool()` as the `cacheMode` parameter. The CLI (`argus assess --no-cache`) already supported these flags via yargs in `cli.ts`. A new `--verbose` flag was also added, detected by `hasVerboseFlag()` and passed through the same pipeline to enable detailed executor logging."""

if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print('✓ Discrepancies: replaced "not wired" with completion text')

# 4. Recommendation
old = """**Recommendation:** The TUI-side flag stripping has been implemented, but the flags are still not wired to the executor's `CacheMode` enum. Either complete the wiring by passing `--no-cache`/`--refresh-cache` through to `CacheMode.NO_CACHE`/`CacheMode.REFRESH` via `ExecutionOptions`, or update ADR-018 to mark the executor-path CLI mapping as \"Partially implemented — TUI only.\""""

new = """**Recommendation:** The cache mode wiring is complete. Flags are fully wired from the TUI prompt and CLI through to the executor's `ExecutionOptions.cacheMode` and into the MCP bridge's `callTool()` parameter. The `--verbose` flag was added as an additional execution option alongside this work. No further action needed for ADR-018 compliance."""

if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print('✓ Recommendation: updated to reflect completion')

# 5. Companion changes
old = """### Companion changes

- **Unit tests added** (14 tests) for `stripFlags()`: covers no flags, single/multiple flags, flags before/after URL, flags-only (empty), whitespace-only, IP:port targets, double-hyphens in URL paths, and flags with `=` values.
- **Test file:** `Argus-Tui/packages/opencode/test/cli/tui/flag-strip.test.ts`"""

new = """### Companion changes

- **Unit tests** (63 total across 2 files) for the full flag-stripping, cache detection, and verbose flag pipeline:
  - `test/cli/tui/flag-strip.test.ts`: 33 tests covering `stripFlags()` (14), `detectCacheMode()` (11), and `hasVerboseFlag()` (8)
  - `test/cli/tui/flag-flow-integration.test.ts`: 30 integration tests covering the combined flow (flag stripping + cache detection + verbose detection together, simulating the exact TUI handler logic), including regression tests (flags don't leak into cleaned target, raw-arg vs stripped-arg distinction) and full round-trip tests"""

if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print('✓ Companion changes: updated test counts and added integration tests')

# 6. Action items - mark cache mode as Fixed
old = '| 🔴 High | Implement full CLI flag mapping (`--no-cache`, `--refresh-cache`) to CacheMode | Backlog |'
new = '| 🔴 High | Implement full CLI flag mapping (`--no-cache`, `--refresh-cache`) to CacheMode | ✅ **Fixed** |'
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print('✓ Action items: cache mode mapping → Fixed')

# 7. Add verbose flag doc action item
old = '| 🟢 Low | Update ADR-022 to mark Phase 3C/3D as "Deferred" | Docs |'
new = '| 🟢 Low | Update ADR-022 to mark Phase 3C/3D as "Deferred" | Docs |\n| 🟢 Low | Document `--verbose` flag in user-facing docs | Docs |'
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print('✓ Action items: added verbose flag doc item')

with open('docs/adr/ARCHITECTURE_AUDIT.md', 'w', encoding='utf-8') as f:
    f.write(content)
print(f'\nArchitecture audit updated: {changes} change(s)\n')

# ── FAILURE_MODE_CHECKLIST.md ──
with open('docs/FAILURE_MODE_CHECKLIST.md', 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# Mark the TUI /assess flag flow as FIXED in §27.2
old = '- [ ] **TUI `/assess` flow ignores flags and corrupts the engagement target** `[M]`'
new = '- [x] **TUI `/assess` flow ignores flags and corrupts the engagement target** `[M]` — **FIXED** — `stripFlags()` strips flags before engagement creation; `detectCacheMode()` detects cache flags; both wired through to `WorkflowRunner.run()`. Full integration tests added (30 tests).'

if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print('✓ §27.2 TUI /assess flag flow: [ ] → [x]')

# Update the Last audited date
old_date = '**Last audited:** 2026-06-22 (seventh-pass: failure-mode checklist updates + flag-strip utility + unit tests) · branch `Argus-Tui`'
new_date = '**Last audited:** 2026-06-22 (eighth-pass: cache mode wiring complete + --verbose flag + integration tests + audit docs) · branch `Argus-Tui`'
if old_date in content:
    content = content.replace(old_date, new_date, 1)
    changes += 1
    print('✓ Updated Last audited date')

with open('docs/FAILURE_MODE_CHECKLIST.md', 'w', encoding='utf-8') as f:
    f.write(content)
print(f'\nFailure mode checklist updated: {changes} change(s)')
