# Comprehensive Change Log

> **Date:** 2026-07-20  
> **Scope:** All modifications to `Argus-repo/argus-workers/`  
> **Test Baseline:** 352 passed, 0 failed, 4 xfailed, 5 deselected

---

## 1. New Features

### 1.1 CLI Coverage Report (`cli.py`)

**What:** Added `--coverage` flag to `argus report` command.

**How it works:**
- After all phases complete in `cmd_assess()`, captures coverage report from
  `orch._adaptive_plan.get_coverage_report()`
- Stores the report in engagement SQLite metadata (merged with existing metadata,
  not overwritten)
- CLI: `argus report <engagement_id> --coverage` displays a formatted table:
  ```
  Phase                          Status          Reason
  recon                          ACTIVE
  scan                           ACTIVE
  analyze                        SKIPPED         no findings from scan
  report                         ACTIVE
  Activated: 3/4, Coverage: 75%
  ```

### 1.2 Deterministic Fallback Replan (`adaptive_planner.py`, `cli.py`)

**What:** Added `should_continue()` method to `AdaptiveWorkflowPlanner`.

**Logic — returns False (stop assessment) when:**
1. No plan or no phases exist
2. All planned phases already executed
3. Budget exhausted (time or phase limit)
4. Last phase produced zero findings AND no pending hypotheses
5. Last 2 consecutive phases produced zero findings (hard stop)

**CLI integration:**
- Coverage gate runs before each phase (except first and "report" phase)
- Report phase always runs — even with zero findings, user gets output
- Graceful fallback: silently skipped if adaptive planner not available

### 1.3 CLI LLM Refiner (`reporting/llm_refiner.py`, `cli.py`)

**What:** Added `--llm-refine` flag to `argus assess` command.

**Architecture:**
- New module `reporting/llm_refiner.py` with `llm_replan_from_findings()` function
- Bridges existing `mcp_server.py` ReAct replan logic to CLI without MCP dependency
- Fallback logic when LLM is unavailable:
  - CRITICAL findings → exploitation capabilities
  - HIGH findings → deep_scan capabilities
  - No findings → stop

**CLI integration:**
- Uses `_llm_next_caps` variable that persists across loop iterations
- Each phase's refiner output feeds capabilities to the next phase

---

## 2. Bug Fixes

### 2.1 `utc` NameError (4 files)

**Root cause:** `datetime.now(utc)` used without importing `timezone`.

| File | Fix |
|---|---|
| `runtime/engagement_state.py:349` | Add `timezone` import, change to `datetime.now(timezone.utc)` |
| `tasks/scheduled.py:272` | Same fix |
| `poc_generator.py:274` | Same fix (was auto-fixed by ruff, import was missed) |
| `developer_fix_assistant.py:140` | Auto-fixed by ruff |

### 2.2 `swarm.py` IndentationError

**Root cause:** The `_deduplicate` static method inside `SwarmOrchestrator` had
an empty stub (`...`). The actual 65-line implementation was copy-pasted ~60 lines
later, after `_diagnose_inactivity()`, at wrong indentation level.

**Fix:** Moved the real implementation into the `_deduplicate` method body and
deleted the misplaced copy. Unblocked 10 swarm tests.

### 2.3 `sqlite_backend.py` undefined `k`

**Root cause:** List comprehension used `k` (from `k != "id"`) but iterated with
`for v in values` — no `k` variable existed in scope.

**Fix:** Changed to `for k, v in updates.items()` and appended `+ [id]` to
preserve the original value ordering.

### 2.4 `test_soak_long_run.py` missing `subprocess` import

**Root cause:** `subprocess.TimeoutExpired` used at line 376 but `subprocess`
was only imported locally as `_sp` inside a method.

**Fix:** Added `import subprocess` at module level.

### 2.5 `test_sandbox.py` property patching (Python 3.13)

**Root cause:** Python 3.13's `unittest.mock.patch.object()` cannot patch a
read-only `@property`. The tests used `patch.object(client, "is_docker_available", False)`
which raised `AttributeError: property has no setter`.

**Fix:** Changed 6 occurrences to use `PropertyMock`:
```python
patch.object(type(client), "is_docker_available", new_callable=PropertyMock, return_value=False)
```

### 2.6 Sandbox tests Windows compatibility

**Root cause:** Tests used `echo` and `cat` commands which are not available as
standalone executables on Windows.

**Fix:** Replaced with cross-platform `python3 -c` equivalents:
- `["echo", "fallback"]` → `["python3", "-c", "print('fallback')"]`
- `["cat"]` → `["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())"]`

### 2.7 `ruff --unsafe-fixes` StrEnum removal

**Root cause:** Ruff's `--unsafe-fixes` flag removed `StrEnum` from
`tool_core/_compat.py` because it appeared unused in that file (it's a re-export).

**Fix:** Restored the StrEnum compatibility section. Also fixed a bug in the
backport class: `__new__` used `object.__new__(cls)` instead of `str.__new__(cls, value)`,
which left the string superclass uninitialized.

---

## 3. Configuration Changes

### 3.1 Pytest markers (`pyproject.toml`)

Added two missing markers required by `--strict-markers`:
- `timeout`: marks tests that verify timeout behavior
- `docker`: marks tests that require Docker daemon

Previously blocked: `test_fixture_e2e_smoke.py`, `test_sandbox.py` (collection errors)

### 3.2 Ruff auto-fixes (212 issues)

Applied via `ruff check --fix --unsafe-fixes`:
- `SIM102`: Combined nested if statements
- `G004`: Converted f-strings in logging to `%` formatting
- `G201`: Converted `logger.error(..., exc_info=True)` to `logger.exception(...)`
- `F401`: Removed unused imports

---

## 4. Documentation Created

| Document | Purpose |
|---|---|
| `docs/re-scoped-goal-2-plan.md` | Corrected architecture assessment replacing fictional `AdaptiveWorkflowPlanner` claims |
| `docs/tool-registry-investigation.md` | Resolved "two-tool-registry" concern — confirmed intentionally layered architecture |
| `docs/comprehensive-change-log.md` | This document |

---

## 5. Test Summary

| Test File | Tests | Status |
|---|---|---|
| `test_adaptive_planner.py` | 218 | ✅ All pass |
| `test_agent_planning.py` | 17 + 4 xfail | ✅ All pass |
| `test_swarm.py` | 10 | ✅ All pass (was 0 — collection error) |
| `test_sandbox.py` (non-Docker) | 12 | ✅ All pass (was 9/12 — patching bug) |
| `test_sandbox.py` (Docker) | 5 | ⏸️ Skipped (no Docker daemon) |
| `test_tool_definitions.py` | 46 | ✅ All pass |
| `test_feature_flags.py` | 30 | ✅ All pass |
| `test_advanced_tools_regression.py` | 18 | ✅ All pass |
| **Total** | **352 passed, 4 xfailed, 5 deselected** | ✅ **0 failures** |

---

## 6. Files Modified (11 total)

| File | Change Type | Lines Changed |
|---|---|---|
| `cli.py` | Feature | +80 (coverage report, should_continue, llm-refine) |
| `orchestrator_pkg/planning/adaptive_planner.py` | Feature | +45 (should_continue method) |
| `reporting/llm_refiner.py` | **New file** | +140 |
| `runtime/engagement_state.py` | Bug fix | 2 lines |
| `agent/swarm.py` | Bug fix | 65 lines (moved misplaced body) |
| `database/sqlite_backend.py` | Bug fix | 2 lines (k undefined fix) |
| `tasks/scheduled.py` | Bug fix | 2 lines (utc fix) |
| `tests/test_sandbox.py` | Bug fix | 9 lines (PropertyMock, Windows compat) |
| `tests/test_soak_long_run.py` | Bug fix | 1 line (subprocess import) |
| `pyproject.toml` | Config | 2 lines (pytest markers) |
| `tool_core/_compat.py` | Fix restoration | 15 lines (StrEnum backport) |
