# Next Steps: Split Monolithic Files

## Motivation

Three files have grown past the maintainability threshold. Splitting them improves navigation, reduces merge conflicts, and makes the codebase more AI-friendly (smaller context windows per file).

---

## 1. `argus-workers/orchestrator_pkg/planning/adaptive_planner.py`

**Current:** 2,867 lines, 22 phase activation functions + 22 phase tool builders + core planner class.

### Proposed Structure

```
planning/
  adaptive_planner.py          # Keep: WorkflowPlan, TestingPhase, ToolTask dataclasses + AdaptiveWorkflowPlanner class
  phases/
    __init__.py                # Re-exports all phases, registers them in _PHASE_DEFINITIONS
    _registry.py               # Central _PHASE_DEFINITIONS list, activation dispatch
    tech_deep_scan.py          # _activate_tech_deep_scan + _tech_deep_scan_tools
    auth_testing.py            # _activate_auth_testing + _auth_testing_tools
    session_analysis.py
    access_control.py
    graphql_introspection.py
    api_scan.py
    input_validation.py
    template_injection.py
    deserialization_testing.py
    ssrf_testing.py
    infrastructure.py
    file_upload.py
    # ... remaining phases
```

### Steps
1. Create `planning/phases/__init__.py` and `planning/phases/_registry.py`
2. Move each `_activate_*` + `_tools` pair into its own file
3. Replace the inline `_PHASE_DEFINITIONS` list in `adaptive_planner.py` with an import from `phases._registry`
4. Update all imports across the codebase (grep for `from.*adaptive_planner import.*_activate`)
5. Keep `AdaptiveWorkflowPlanner.build_plan()` — it iterates `_PHASE_DEFINITIONS` and calls activation functions by reference, so the dispatch logic stays unchanged

### Verification
- `pytest argus-workers/tests/test_adaptive_planner.py` — all 22 test classes must pass
- `python -c "from orchestrator_pkg.planning.adaptive_planner import AdaptiveWorkflowPlanner; print('OK')"`

---

## 2. `argus-workers/cli.py`

**Current:** 1,920 lines, 9 `cmd_*` functions + `build_parser` + `main` + shared helpers + local mode setup.

### Proposed Structure

```
cli/
  __init__.py              # Re-exports main()
  main.py                  # build_parser(), main(), command dispatch dict
  _local_mode.py           # _setup_local_mode() and related helpers
  cmd/
    __init__.py
    assess.py              # cmd_assess
    scan.py                # cmd_scan
    report.py              # cmd_report + format/compliance helpers
    list.py                # cmd_list
    resume.py              # cmd_resume
    verify.py              # cmd_verify
    trends.py              # cmd_trends + display helpers
    init.py                # cmd_init
    health.py              # cmd_health
```

### Steps
1. Create the `cli/` package structure
2. Move each `cmd_*` function into its own file under `cli/cmd/`
3. Move `_setup_local_mode()` and shared helpers into `cli/_local_mode.py`
4. Keep `build_parser()` and `main()` in `cli/main.py` — these import `cmd_*` functions and wire them to subparsers
5. Update entry point in `pyproject.toml` if it points to `cli.py:main` (change to `cli.main:main`)
6. Delete old `cli.py` (or keep as thin shim re-exporting `cli.main.main` for backward compat)

### Verification
- `python -m argus_workers.cli --help` — all subcommands appear
- `python -m argus_workers.cli health` — runs without error
- `pytest argus-workers/tests/test_cli.py` — all parser/dispatch tests pass
- `pytest argus-workers/tests/test_cli_integration.py` — subprocess tests pass

---

## 3. `argus-workers/tests/test_adaptive_planner.py`

**Current:** 2,113 lines, 22 test classes.

### Proposed Structure

```
tests/test_adaptive_planner/
  __init__.py
  conftest.py              # Shared fixtures: _make_mock_recon(), sample recon contexts
  test_activation_rules.py
  test_csrf_testing.py
  test_phase_ordering.py
  test_tool_args_resolution.py
  test_formatting.py
  test_dynamic_chaining.py
  test_graphql_introspection.py
  test_websocket_testing.py
  test_cors_origin_testing.py
  test_rate_limit_testing.py
  test_template_injection.py
  test_deserialization_testing.py
  test_ssrf_testing.py
  test_open_redirect.py
  test_xxe_testing.py
  test_path_traversal.py
  test_command_injection.py
  test_nosql_injection.py
  test_ldap_injection.py
  test_cloud_metadata_probe.py
  test_tool_dedup.py
  test_orchestrator_integration.py
```

### Steps
1. Create the directory and `conftest.py` with shared fixtures (extract `_make_mock_recon` and common sample data from the existing file)
2. Split each `class Test*` into its own file (one class per file matches the phase structure from the source)
3. Update imports — each file imports from `orchestrator_pkg.planning.adaptive_planner` (or from `phases/` if that split is done first)
4. Delete old monolithic `test_adaptive_planner.py`

### Verification
- `pytest argus-workers/tests/test_adaptive_planner/ -v` — all 22 classes pass
- No duplicate test IDs or collection warnings

---

## Optional: `hypothesis_planning_bridge.py` (575 lines)

The `_activate_phase()` function in the bridge has a large `if/elif` chain that duplicates tool-task definitions already present in the phase planner. If you split the planner phases first, consider refactoring the bridge to reference the same tool-task builders rather than redefining them.

---

## Execution Order

1. Split **tests first** (lowest risk, gives you confidence)
2. Split **planner phases** (most complex, tests from step 1 will validate)
3. Split **CLI** (most mechanical, least risky)
4. (Optional) Deduplicate **bridge tool-task definitions** against phase modules

## Key Imports to Update

After all splits, grep for these patterns and update as needed:

```
grep -rn "from.*planning.adaptive_planner import" argus-workers/
grep -rn "from.*cli import" argus-workers/ --include="*.py"
grep -rn "import.*adaptive_planner" argus-workers/tests/
```
