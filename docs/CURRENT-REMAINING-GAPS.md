# Argus Current Remaining Gaps

> **Status:** Current gap register
>
> **Verified:** 2026-09-01
>
> **Purpose:** Record the work that remains before Argus can honestly be described as fully autonomous, production-grade AI red-team pentesting software.
>
> **Evidence policy:** This document is based on current source, configuration, and test evidence. Existing plans and historical completion reports are not treated as proof. A component existing in the repository does not by itself prove that the complete end-to-end behavior works.

## Critical blockers

### 1. Full test suite is not clean

The last full Python worker-suite run reported:

- 4,908 passed
- 55 skipped
- 7 xfailed
- 27 xpassed
- 4 unexpected failures

Three failures were collection-order contamination in the full-scan E2E tests:

```text
AttributeError: 'function' object has no attribute 'run'
```

Affected tests:

- `test_phase_analyze_transitions_and_dispatches_report`
- `test_chain_error_report_raises`
- `test_full_pipeline_chain`

The issue is cached `tasks.analyze` state after mocked imports. A focused batch also reproduced this intermittently: 76 passed and 3 failed.

The fourth previously reported failure was:

- `tests/test_db_connection.py::test_tenant_context_failure_logs_warning`

It passed in isolation, indicating shared singleton or collection-order contamination rather than a stable isolated defect.

### 2. Autonomous execution is not fully proven

Argus has agent, planner, MCP, and replan components, but code existence is not equivalent to end-to-end autonomy.

Still requiring proof:

- automatic signal-driven deep-scan dispatch,
- automatic post-exploitation dispatch,
- automatic auth-focused scanning after recon detects login/auth endpoints,
- deterministic fallback replanning,
- attack-graph-to-execution feedback,
- behavior when the LLM is unavailable or returns malformed tool calls,
- stopping and recovery behavior after repeated tool failures.

Some execution paths still degrade to deterministic execution or stop rather than autonomously recover and continue.

### 3. Tool availability is operationally incomplete

The Python registry reports missing entries in some paths, including:

- `browser_security_operator`
- `register`

External binaries such as Nuclei, Nmap, SQLMap, WhatWeb, Subfinder, and others still depend on host or container provisioning.

The provisioning system exists, but deployment readiness still depends on:

- installing the binaries,
- verifying versions and checksums,
- ensuring templates and data are present,
- testing the exact target environment,
- making missing-tool behavior visible and intentional.

## Major feature gaps

### 4. Rich TUI architecture is incomplete

The TypeScript Argus layer exists, but the target architecture is not fully realized.

Notably:

- `src/argus/tui/app.tsx` is absent.
- Some routes exist as CLI alternatives rather than full TUI routes.
- Settings, terminal, rich asset/evidence browsing, and complete report UX remain partial or deferred.
- OpenCode runtime remnants and branding remain in parts of the TUI.

### 5. Report export is incomplete

The HTML renderer exists, but the full export architecture still needs end-to-end verification:

- dedicated exporter behavior,
- complete `--format` handling,
- `--open` browser behavior,
- JSON/Markdown/HTML consistency.

### 6. Attack-chain visualization is mostly a plan

The backend attack graph exists, but the documented interactive visualization is not fully implemented or proven:

- no proven complete Python-to-TUI visualization bridge,
- no fully verified interactive graph UI,
- no complete chain drill-down and evidence experience,
- no proven real-time chain-discovery rendering.

### 7. Advanced security tools are not all implemented

The advanced-tools plan describes approximately 14 composite systems, including:

- browser security operator,
- attack-surface mapper,
- evidence intelligence engine,
- threat-intelligence aggregator,
- vulnerability knowledge engine,
- finding-correlation engine,
- attack-path generator,
- infrastructure-security analyzer,
- assessment orchestrator,
- verification agent,
- workflow analytics,
- engagement analytics.

Some primitives and similarly named modules exist, but the complete composite architecture described in the plan is not fully implemented and verified.

## Security and autonomy limitations

### 8. Active-defense resilience is unproven

The adversarial evaluation plan is not an executed test system. The following remain unproven against real defended targets:

- WAF detection and adaptive behavior,
- rate-limit compliance,
- honeypot and deception detection,
- prompt-injection handling from target content,
- gradual target degradation,
- large-response and data-flood handling.

### 9. Exploitation and lateral movement remain limited

Argus supports post-exploitation concepts and attack-chain planning, but true fleet-scale red teaming is not yet a first-class workflow.

Remaining limitations include:

- single-target-centric orchestration,
- incomplete multi-host asset-graph execution,
- limited lateral-movement automation,
- limited session rotation,
- no generalized adaptive-encoding pipeline,
- no robust blockade/deception model,
- exploit scripts that may be generated but are not universally executed as verified actions.

### 10. Evidence chain-of-custody is incomplete in depth

Hashing and integrity verification exist, but complete forensic-chain proof still needs operational validation for:

- operator identity,
- source-tool and phase metadata in every path,
- parent-finding relationships,
- append-only and auditable event history,
- signed authenticity rather than integrity-only hashes,
- encrypted artifact lifecycle and recovery.

### 11. Production LLM reliability is not proven at scale

Fallbacks and retry logic exist, but these areas remain insufficiently validated:

- malformed JSON and tool-call recovery under real provider responses,
- rate-limit handling across providers,
- provider failover,
- token and cost accuracy,
- long-running context retention,
- prompt-injection resistance against adversarial target data,
- degraded-mode reporting visible to operators.

## Testing and CI gaps

### 12. CI does not yet prove a clean full suite

The randomized collection-order job is currently non-blocking:

```yaml
continue-on-error: true
```

It reports fragility but does not block merges.

The standard CI path also excludes or schedules separately:

- database tests,
- Redis tests,
- E2E tests,
- Docker tests,
- fixture and full-matrix tests.

This is operationally reasonable, but it is not equivalent to proving that all tests pass on every change.

### 13. Skips, xfails, and xpasses need cleanup

The 55 skipped and 7 xfailed tests need classification into:

- intentionally environment-gated,
- obsolete,
- genuinely unsupported,
- or blocked by incomplete CI setup.

The 27 xpasses should be reviewed and either:

- converted into normal passing tests,
- or made strict so regressions become visible.

### 14. Benchmark and soak validation remain incomplete

Infrastructure exists for:

- false-negative benchmarking,
- long-run drift testing,
- memory, cost, and quality monitoring.

Ground-truth manifests, real target runs, and validated baseline results are still missing.

## Documentation and governance

### 15. Documentation is labeled but not fully normalized

All current documentation files have current-status notices, but many historical documents still contain stale internal claims and counts. They are clearly labeled as historical, yet remain confusing unless individually rewritten or archived.

### 16. Governance is documented, not operationally enforced

The following still require real organizational action:

- signed authorization workflow,
- incident-response rehearsal,
- dated reviewer sign-off,
- license and legal review,
- retention-policy enforcement review,
- insurance and liability decisions,
- third-party penetration testing,
- organizational readiness review.

## Practical completion order

The highest-value sequence is:

1. Make collection-order behavior deterministic and remove the remaining full-suite failures.
2. Establish a reproducible, clean CI baseline across the relevant service-backed suites.
3. Prove the complete scan path with provisioned binaries against controlled vulnerable targets.
4. Verify automatic deep-scan, auth-scan, exploitation, replanning, and reporting dispatch.
5. Execute active-defense, false-negative, and long-run soak evaluations.
6. Finish or explicitly narrow the TUI, report-export, and attack-visualization scope.
7. Convert governance templates into executed organizational controls.

Until these items are closed with source-level and runtime evidence, Argus should be described as a substantial security-assessment platform with partial autonomous capabilities—not as fully autonomous red-team software.