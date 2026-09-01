> **Current-status notice (verified 2026-09-01):** This document is a dated decision, plan, audit, or historical record. Its completion claims are not a current implementation guarantee; current source, configuration, and tests are authoritative.

# Argus — Documentation Index

Technical documentation and reference for the Argus security assessment platform.

> **Current-status policy (verified 2026-09-01):** Documents in this directory are a mixture of architecture decisions, implementation plans, dated audits, and historical session reports. A status marker in a historical document is not proof of the current implementation. Current source, configuration, and tests are authoritative.

## Current verification snapshot

- `docs/` contains **68 Markdown/text files** including 24 ADRs, governance material, and a documentation script.
- `argus-workers` currently contains **68 tool-definition YAML files** and **76 registered Python tools**.
- The Python generated-definition check passes: `scripts/generate_tool_defs.py --check`.
- Python/TypeScript tool-alignment validation passes: `scripts/validate_tool_alignment.py --check`.
- The focused regression set covers scheduled tasks, mocked Celery imports, orchestration, and the full-scan E2E path. One invocation passed **76/79**; the remaining 3 failures are the known collection-order `tasks.analyze` cache contamination (`'function' object has no attribute 'run'`) and are not being hidden by this documentation update.
- The full worker-suite result previously recorded in this checkout was **4,908 passed, 55 skipped, 7 xfailed, 27 xpassed, and 4 failures**. Do not use older zero-failure or older test-count claims as the current baseline.
- The randomized collection-order CI job is intentionally **non-blocking** while remaining collection-order issues are investigated.

## Document categories

| Area | Documents |
|---|---|
| Architecture and decisions | `ARCHITECTURE_*.md`, `adr/`, tool-registry documents |
| Plans and designs | `*-plan.md`, `implementation-order.txt`, design/prompts |
| Audits and reports | `70-*`, `80-*`, `BUG_SWEEP_REPORT.md`, readiness/autonomy reports |
| Operations and governance | `DB_VOLUME_CLEANUP.md`, `FAILURE_MODE_CHECKLIST.md`, `governance/` |
| Historical records | `comprehensive-change-log.md`, `session-progress-2026-07-13.md`, workstream reports |

## Important interpretation rules

1. A plan describes intended work; it does not establish that the work exists.
2. A dated audit reports what was observed at that date and may be stale.
3. A checkbox is not accepted as evidence without source/configuration/test verification.
4. Environment-dependent tests and external tools must be reported separately from code failures.
5. Destructive operational instructions, especially Docker volume cleanup, must not be run without explicit confirmation.

See each document's current-status notice for its verification scope.