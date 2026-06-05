# Test Coverage Expansion Plan

> **Status: ✅ All 9 phases complete.** See [`progress.md`](progress.md) for the full report of 37 new test files and results.

**Goal:** Raise Python coverage from ~50% to ~70%+ and achieve ~85%+ on TypeScript business logic.

## Phases

### Phase 1: Python — High-Impact / Zero-Coverage Files
- **1a:** `ai_explainer.py` (300 lines, 0%)
- **1b:** `orchestrator_pkg/analysis/` (5 files, all 0%)
- **1c:** `orchestrator_pkg/persistence/finding_persistence_service.py` (170 lines, 0%)
- **1d:** `orchestrator_pkg/reporting/` (3 files, 0%)
- **1e:** `orchestrator_pkg/custom_rules/custom_rules_service.py` (35 lines, 0%)

### Phase 2: Python — Database Repositories (7 files at 0%)
- `agent_decision_repository.py`, `ai_explainability_repository.py`, `engagement_events_repository.py`, `pgvector_repository.py`, `report_repository.py`, `tool_accuracy_repository.py`, `engagement_repository.py` (top up)

### Phase 3: Python — Tasks (6 files at 0%)
- `bugbounty.py`, `maintenance.py`, `posture.py`, `replay.py`, `scheduled.py`, `self_scan.py`

### Phase 4: Python — Tools (11 files at 0%)
- Key ones: `arjun_scanner.py`, `bugbounty_report_generator.py`, `context.py`, `ffuf_scanner.py`, `finding_verifier.py`, `tool_result.py`, `update_nuclei_templates.py`, `_browser_scan_worker.py`, etc.

### Phase 5: Python — Models (3 files at 0%)
- `candidate_list.py`, `feedback.py`, `pycache entires`

### Phase 6: Python — Top-up existing low-coverage files
- `mcp_transport.py`, `celery_worker_launcher.py`, etc.

### Phase 7: TypeScript — Untested Business Logic
- `workflow-runner.ts`, `evidence/store.ts`, `config/loader.ts`, `chained-scenario.ts`, `ui.ts`, `cli.ts`, `commands/report.ts`

### Phase 8: TypeScript — TUI Components
- `tui-commands.ts`, `tui-command-registry.tsx`, `scan-store.ts`, `navigator.ts`, route files

### Phase 9: Verify & Report
- Run all tests, check coverage, report final numbers

## Progress
- Phase 1: ✅ Complete
- Phase 2: ✅ Complete
- Phase 3: ✅ Complete
- Phase 4: ✅ Complete
- Phase 5: ✅ Complete
- Phase 6: ✅ Complete
- Phase 7: ✅ Complete
- Phase 8: ✅ Complete
- Phase 9: ✅ Complete
