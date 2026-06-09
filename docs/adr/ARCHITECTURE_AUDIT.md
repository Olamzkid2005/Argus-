# Architecture Audit Report

**Date:** 2026-06-09
**Scope:** ADR-018 through ADR-024 verification + pipeline tool side-effect audit

---

## Summary

| Check | Result | Issues |
|-------|--------|--------|
| ADR-018 (Cache Mode Semantics) | ⚠️ Partial | CLI flags not implemented |
| ADR-019 (File Cache Rejection) | ✅ Clean | Design record only |
| ADR-020 (Error Hint Architecture) | ✅ Clean | Matches code exactly |
| ADR-021 (Streaming Error Events) | ✅ Clean | Matches code exactly |
| ADR-022 (Fixture Testing Strategy) | ⚠️ Partial | Only sub-phases 3A/3B done |
| ADR-023 (Tool Definition Boundaries) | ⚠️ Bug | Duplicate risk mismatch check in validator |
| ADR-024 (Report Export Architecture) | ⚠️ Partial | Exporter module not implemented |
| Pipeline tool side effects | ✅ Clean | Domain-appropriate; no architectural violations |

**Bug found:** `validate_tool_alignment.py` — duplicate `_is_destructive()` risk check block (now fixed).

---

## ADR-018: Cache Mode Semantics

### Claims vs Code

| Claim | Status | Code Location |
|-------|--------|---------------|
| CacheMode enum (NORMAL/NO_CACHE/REFRESH) | ✅ | `cache.py:31-38` |
| Enforcement at execution layer (tool_runner) | ✅ | `tool_runner.py:341` |
| CLI mapping (`--no-cache`, `--refresh-cache`) | ❌ Not implemented | `executor.ts` has `ExecutionOptions` type but it's unwired |
| Observability counters (hit/miss/bypass/refresh) | ✅ | `cache.py:124-145` |
| -1 TTL sentinel for no-expiry | ✅ | `cache.py:96-98` |

### Discrepancies

**CLI flags not wired.** ADR-018 describes how `--no-cache` and `--refresh-cache` flags map to `CacheMode.NO_CACHE` and `CacheMode.REFRESH`. The TypeScript `ExecutionOptions` interface with `cacheMode` exists in `executor.ts` but is never connected to any CLI command handler or tool invocation path. The pipeline router (`pipeline_router.py`) defaults to `cache_mode=None` — the CLI binding layer is missing.

**Recommendation:** Either implement the CLI flags, or update ADR-018 to mark the CLI mapping as "Planned — not yet implemented."

---

## ADR-019: File Cache Fallback — Rejected

### Claims vs Code

| Claim | Status | Code Location |
|-------|--------|---------------|
| Local JSON file cache not implemented | ✅ | `cache.py` is Redis-only |
| Redis graceful `None` return is sufficient | ✅ | `_get_redis()` returns `None` when unavailable |
| Encryption/path-traversal concerns documented | ✅ | ADR text |

No discrepancies. Design record only.

---

## ADR-020: Error Hint Architecture

### Claims vs Code

| Claim | Status | Code Location |
|-------|--------|---------------|
| error_hints.py is pure presentation layer | ✅ | `error_hints.py` consumes `error_classifier.py` |
| Cannot independently classify errors | ✅ | No re-implemented classification logic |
| Three-tier priority (ErrorCode → Category → Generic) | ✅ | `hint_for_classification()` in `error_hints.py:217-251` |
| Hint generation never crashes tools | ✅ | `build_error_hint()` wraps in try/except (`error_hints.py:275`) |
| 20 ErrorCode hints + 10 category fallbacks + tool-specific | ✅ | `_ERROR_CODE_HINTS` (20 codes), `_CATEGORY_FALLBACK_HINTS` (10 cats), `_TOOL_SPECIFIC_PATTERNS` (5 tools) |

No discrepancies. Implementation matches ADR exactly.

---

## ADR-021: Streaming Error Events

### Claims vs Code

| Claim | Status | Code Location |
|-------|--------|---------------|
| ERROR_HINT as separate event type from ERROR | ✅ | `EventType.ERROR_HINT` in `streaming.py:52` |
| Bypasses transactional stream | ✅ | `emit_error_hint()` calls `get_stream_manager().publish()` directly — no `_maybe_transactional()` check |
| Includes tool/error_id metadata | ✅ | `hint.to_dict()` provides `tool` and `error_id` fields |

No discrepancies. Implementation matches ADR exactly.

---

## ADR-022: Fixture Testing Strategy

### Claims vs Code

| Claim | Status | Code Location |
|-------|--------|---------------|
| Phase 3A: Test CI infrastructure | ✅ | `requirements-dev.txt`, `lint.yml` python-tests job |
| Phase 3B: Static JSON fixtures | ✅ | 6 fixture JSONs + 3 error output JSONs in `test_fixtures/` |
| Phase 3C: E2E expansion using Selenium/Playwright | ❌ Not implemented | — |
| Phase 3D: Performance benchmarks and regression gates | ❌ Not implemented | — |
| conftest.py helpers (load_fixture, get_fixture_path) | ✅ | `tests/conftest.py:18-41` |
| Pipeline regression tests (17 tests, <5s) | ✅ | `test_fixture_pipeline.py` |

### Discrepancies

ADR-022 describes all 4 sub-phases (3A-3D) as part of the fixture testing strategy. Only 3A and 3B are implemented. The ADR text explicitly mentions 3D's scope (CI comparison benchmarks, regression gates) and 3C's scope (Selenium MFA, secondary email verification), but neither exists in the codebase.

**Recommendation:** Either implement 3C/3D, or update ADR-022 to mark them as "Planned — deferred."

---

## ADR-023: Tool Definition Boundaries

### Claims vs Code

| Claim | Status | Code Location |
|-------|--------|---------------|
| Python YAML = execution domain | ✅ | 65 files in `tools/definitions/*.yaml` |
| TUI YAML = workflow domain | ✅ | `Argus-Tui/.../tool-definitions.yaml` |
| Validate overlap, don't generate one from the other | ✅ | `validate_tool_alignment.py` |
| Checks capabilities + risk_level consistency | ✅ | Capability diff + risk mismatch detection |

### Bug Found (Fixed)

The `validate()` function in `validate_tool_alignment.py` contained a **duplicate risk mismatch check** — the `_is_destructive()` validation block appeared twice in succession (lines 97-108 and 110-121). Any tool with a risk mismatch would produce **two identical error messages** instead of one. Fixed by removing the duplicate block.

---

## ADR-024: Report Export Architecture

### Claims vs Code

| Claim | Status | Code Location |
|-------|--------|---------------|
| Pure renderers at library layer | ✅ | `html_report.py` — pure function, no I/O |
| File I/O at application boundary | ❌ Not implemented | `reporting/__init__.py` exists but no `report_saver` module |
| Browser launch at CLI only | ❓ Not verifiable | CLI layer not reviewed |
| render_html_report() is pure | ✅ | No file I/O, no subprocess calls, no browser launches |

### Discrepancies

**Missing exporter module.** ADR-024 describes a `report_saver` module at the application boundary that handles:
- File writing
- Output path resolution
- Format selection
- Browser launching

The `reporting/__init__.py` was created as a package but contains only a docstring with no exporter module. Meanwhile, `bugbounty_report_generator.py` performs file I/O directly in its `main()` function (`open(findings_path)`, `output_path.write_text()`). This side effect is within the CLI `main()` entry point, which is acceptable per the ADR's principle ("file I/O at application boundary"), but a dedicated exporter/report-saver module would provide a reusable abstraction.

**Recommendation:** Create `reporting/exporter.py` with a `save_report(html: str, path: str, open_browser: bool = False)` function. This would move file I/O out of ad-hoc CLI code and into the architecture's defined boundary.

---

## Pipeline Tool Side Effects

### Principle (from ADR-024)

> Pipeline tools stay side-effect-free — pure renderers at library layer; side effects at CLI boundary.

### Tools with Side Effects

| Tool | Side Effect | Domain-Appropriate? |
|------|------------|---------------------|
| `bugbounty_report_generator.py` | `open()`, `write_text()` in CLI `main()` | ✅ — CLI entry point only |
| `threat_intelligence_aggregator.py` | `urlopen()`, `subprocess.run(["whois"])` | ✅ — TI aggregator expected |
| `update_nuclei_templates.py` | `subprocess.run()` | ✅ — Template updater expected |
| `browser_scanner.py` | `subprocess.run()` | ✅ — Browser automation expected |
| 20+ tools with `requests`/`httpx` sessions | HTTP calls to targets | ✅ — Security scanners expected |
| `executive_report_generator.py` | None (pure data transformation) | ✅ |

### Verdict

No architectural violations found. All side effects are domain-appropriate:
- **Security scanners** must make HTTP requests and run subprocesses — that's their intrinsic function
- **Report generators** read inputs and write outputs within their CLI `main()` boundaries
- The "pure renderer" principle correctly applies to the `reporting/` package specifically

---

## Action Items

| Priority | Item | Owner |
|----------|------|-------|
| 🔴 High | Implement CLI flag mapping (`--no-cache`, `--refresh-cache`) to CacheMode | Backlog |
| 🟡 Medium | Remove duplicate risk check in `validate_tool_alignment.py` | ✅ **Fixed** |
| 🟡 Medium | Create `reporting/exporter.py` with `save_report()` function | Backlog |
| 🟢 Low | Update ADR-018 to note CLI flags as "Planned" | Docs |
| 🟢 Low | Update ADR-022 to mark Phase 3C/3D as "Deferred" | Docs |
