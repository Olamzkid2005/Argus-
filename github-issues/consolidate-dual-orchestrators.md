# Consolidate Dual Orchestrator Implementations

**Priority:** P1 (Architecture)
**Labels:** `refactor`, `tech-debt`, `consolidation`, `good-first-issue`
**Estimated effort:** 2–3 hours (excl. testing)
**Risk:** Low — the shim is a pure re-export, so no behavior changes

---

## Problem

The codebase contains **two import paths** for the `Orchestrator` class, causing developer confusion over which to use:

| Path | Location | Size | Role |
|------|----------|------|------|
| `from orchestrator import Orchestrator` | `argus-workers/orchestrator.py` | **18 lines** | Backward-compat shim that re-exports from `orchestrator_pkg` |
| `from orchestrator_pkg import Orchestrator` | `argus-workers/orchestrator_pkg/__init__.py` | **6 lines** | Package `__init__` that re-exports from `.orchestrator` |
| `from orchestrator_pkg.orchestrator import Orchestrator` | `argus-workers/orchestrator_pkg/orchestrator.py` | **~1300 lines** | The **real implementation** |

The root-level `orchestrator.py` was created when the orchestrator was extracted into the `orchestrator_pkg/` package, left as a migration shim. It also re-exports three utility functions (`get_wordlist_path`, `get_nuclei_templates_path`, `tool_timeout`) from `orchestrator_pkg/utils.py`.

**The shim has been in place long enough that all callers should have migrated.** Keeping it adds cognitive overhead — developers see `orchestrator.py` AND `orchestrator_pkg/` side by side in the tree and don't know which to import from.

---

## Current Importers

### P0: Production code importing from root `orchestrator`

| File | Import | Impact |
|------|--------|--------|
| `tasks/base.py` (line 130) | `from orchestrator import Orchestrator` | **Must update** — core production path |
| `tests/test_orchestrator_integration.py` | `from orchestrator import Orchestrator` | **Must update** |
| `tests/test_repo_scan_integration.py` | `from orchestrator import Orchestrator` | **Must update** |

### P1: Test code already using package path (consistent — leave as-is)

| File | Import |
|------|--------|
| `tests/test_wiring_logging.py` | `from orchestrator_pkg.orchestrator import Orchestrator` |

### Other `orchestrator_pkg` imports (not affected)

These import from other modules within the package — they're already using the canonical path:

| File | Import |
|------|--------|
| `tests/test_rate_limit_repository.py` | `from orchestrator_pkg.scan import ...` |
| `tests/test_sca_scan.py` | `from orchestrator_pkg.repo_scan import ...` |
| `tests/test_scanning_pipeline.py` | `from orchestrator_pkg.scan import ...` |
| `tests/test_full_scan_pipeline_e2e.py` | `from orchestrator_pkg.orchestrator import ...` |
| `agent/swarm.py` | `from orchestrator_pkg.utils import ...` |
| `orchestrator_pkg/recon.py` | `from .utils import ...` (relative) |
| `orchestrator_pkg/scan.py` | `from .utils import ...` (relative) |

### Utility function callers (not importing from root shim)

The root shim re-exports `get_wordlist_path`, `get_nuclei_templates_path`, and `tool_timeout`, but **no production code imports them from the root shim**. All callers already use the package path:

| File | Import Path |
|------|-------------|
| `agent/swarm.py` | `from orchestrator_pkg.utils import get_nuclei_templates_path` |
| `orchestrator_pkg/recon.py` | `from .utils import get_wordlist_path` (relative) |
| `orchestrator_pkg/scan.py` | `from .utils import get_nuclei_templates_path` (relative) |

---

## Proposed Plan (4 Steps, Ordered by Priority)

### Step 1 — Update production import in `tasks/base.py`

**File:** `tasks/base.py`, line 130

**Change:**
```python
# Before
from orchestrator import Orchestrator

# After
from orchestrator_pkg import Orchestrator
```

**Importance:** This is the single production code path that uses the shim. Every Celery task routes through `task_context()`, which instantiates `Orchestrator` via this import. Once this is updated, the shim is only used by tests.

### Step 2 — Update test imports

**Files:**
- `tests/test_orchestrator_integration.py`
- `tests/test_repo_scan_integration.py`

**Change:** Replace `from orchestrator import Orchestrator` with `from orchestrator_pkg import Orchestrator` in both files.

Note: `tests/test_orchestrator_integration.py` currently uses `from orchestrator import Orchestrator` inside `with patch.object(some_module, ...)` blocks. Verify the patching still works after the import path change — the patches target test-internal references, not module-level `orchestrator` imports, so they should be unaffected.

### Step 3 — Remove the root-level `orchestrator.py` shim

**File:** `argus-workers/orchestrator.py` (delete)

After Steps 1–2, no code imports from this file. The shim can be safely deleted.

**What gets deleted:**
- The `Orchestrator` re-export
- The three utility re-exports (`get_wordlist_path`, `get_nuclei_templates_path`, `tool_timeout`) — these are not used by any caller via this path
- The docstring and `__all__` list

### Step 4 — Clean up `orchestrator_pkg/__init__.py`

**File:** `orchestrator_pkg/__init__.py`

The `__init__.py` currently re-exports `Orchestrator`. Consider whether to also export the utility functions for a cleaner public API. This is optional and low-priority.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Circular import**: `tasks/base.py` → `orchestrator_pkg/__init__.py` → `orchestrator_pkg/orchestrator.py` imports from `tasks.utils` (via `load_recon_context`, `save_recon_context`) | Already works with the shim — no new dependencies are added. The import chain is the same, just one level shorter. |
| **Test patching breaks**: Tests patch `orchestrator.X` but import from `orchestrator_pkg.Y` | Step 2 handles this. The patches in existing tests target module locals, not the `orchestrator` shim. |
| **Undocumented import**: Someone imports from the removed shim | This is tracked in the issue. CI will fail immediately with `ModuleNotFoundError` if any non-updated file imports from the removed module. |
| **Runtime warning for backward compat**: Should we add a deprecation warning before deleting? | The shim is internal — no external API consumers. A deprecation warning step would add noise with no benefit. We can delete directly after updating all callers. |

---

## Verification

1. **Type check:** Run `mypy argus-workers/` — no import errors
2. **Lint:** Run `ruff check argus-workers/` — no unused-import errors
3. **Tests:** Run `pytest argus-workers/tests/test_orchestrator_integration.py argus-workers/tests/test_repo_scan_integration.py argus-workers/tests/test_wiring_logging.py` — all pass
4. **Smoke test:** Verify that `from orchestrator import Orchestrator` now raises `ModuleNotFoundError`
5. **Utility import smoke test:** Verify the three re-exported utils still work from their canonical package path:
   ```python
   from orchestrator_pkg.utils import get_wordlist_path, get_nuclei_templates_path, tool_timeout
   ```
6. **Full test suite:** Run `pytest argus-workers/tests/` — no regressions

---

## File Change Summary

```
M  tasks/base.py          # 1 line: import path change
M  tests/test_orchestrator_integration.py  # N lines: import path change
M  tests/test_repo_scan_integration.py     # N lines: import path change
D  orchestrator.py        # Delete 18-line shim
?  orchestrator_pkg/__init__.py  # Optional cleanup
```

---

## Discussion Points

1. **Should we add a deprecation warning for one release cycle?** The shim has been in place for several months — all callers should have migrated. Adding a deprecation warning just adds log noise. Recommend: direct deletion.
2. **Should we also export utility functions from `orchestrator_pkg/__init__.py`?** Currently they're only available via `orchestrator_pkg.utils`. No production code needs them at the package level. Recommend: keep as-is.
3. **Should we rename `orchestrator_pkg` to just `orchestrator`?** This would be a larger rename. The current consolidation stops at removing the duplicate shim, not renaming the canonical location.
