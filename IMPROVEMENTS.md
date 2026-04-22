# Argus Platform — Comprehensive Improvement Recommendations

> Deep codebase audit. No Docker/deployment suggestions. All actionable within current architecture.

---

## 1. User Experience (UX)

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 1.1 | Settings loading flash | `src/app/engagements/page.tsx:71` | Add `settingsLoading` state + shimmer | 30m | High |
| 1.2 | No target history | `src/app/engagements/page.tsx` | Store last 5 URLs in localStorage as chips | 45m | Medium |
| 1.3 | Empty dashboard | `src/app/dashboard/page.tsx` | Add `<EmptyStateOnboarding />` with one-click templates | 2h | High |
| 1.4 | No bulk findings actions | `src/app/findings/page.tsx` | Add checkboxes + bulk verify/delete + confidence filter slider | 3h | High |
| 1.5 | No keyboard shortcuts | `src/hooks/` | `useKeyboardShortcuts`: Cmd+K palette, Cmd+N new, ? help | 2h | Medium |
| 1.6 | Toast ID collisions | `src/components/ui/Toast.tsx:28` | Use `crypto.randomUUID()`, max 5 stack, progress bar, ARIA | 1h | Medium |
| 1.7 | Vague scan progress | ScannerActivityPanel | Visual stepper: Recon→Discovery→Vuln→Analysis→Report | 4h | High |
| 1.8 | Chart colors ignore theme | Analytics pages | `useThemeColors()` hook reading CSS vars | 1.5h | Low |
| 1.9 | CVE/CWE not clickable | Finding detail | Copy button + NVD/MITRE links | 45m | Low |
| 1.10 | No quick navigation | - | Cmd+K command palette (cmdk already in deps) | 3h | Medium |

---

## 2. Website Scanning

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 2.1 | Missing modern vulns | `tools/web_scanner.py:34` | Add GraphQL introspection, JWT alg confusion, prototype pollution, cache poisoning, HTTP smuggling, DOM XSS, OpenAPI discovery | ~10h | High |
| 2.2 | Blind payload firing | `tools/web_scanner.py` | `differential_check()`: baseline→payload→compare hash/reflectivity (~60% FP reduction) | 3h | High |
| 2.3 | No WAF detection | `tools/web_scanner.py` | `detect_waf()`: check CF-RAY, x-mod-security, blocked strings. Tag findings `waf_interference: true` | 2h | High |
| 2.4 | Hardcoded params | `tools/web_scanner.py` | Feed discovered forms/params from katana crawl into injection tests | 2h | Medium |
| 2.5 | No time-based detection | `tools/web_scanner.py` | Add SLEEP payloads for SQL/Command injection timing attacks | 1.5h | Medium |
| 2.6 | `verify=False` globally | `tools/web_scanner.py` | Remove `verify=False`, use proper SSL verification with option to disable per-target | 30m | High |
| 2.7 | No rate limiting per endpoint | `tools/web_scanner.py` | Per-endpoint rate limiting (currently only global) | 1h | Medium |
| 2.8 | Missing response analysis | `tools/web_scanner.py` | Parse HTTP status codes, content-type, response size for fingerprinting | 1h | Low |

---

## 3. Repository Scanning

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 3.1 | No dependency scanning (SCA) | `tasks/repo_scan.py` | Add npm audit, pip-audit, govulncheck, Maven Central checks. Store as `DEPENDENCY_VULNERABILITY` | 6h | High |
| 3.2 | No git history secret scan | `tasks/repo_scan.py` | Run `git log --all --patch` for committed secrets (trufflehog-style) | 2h | High |
| 3.3 | No commit blame timeline | `tasks/repo_scan.py` | `git blame` findings to show introduced_at, author, commit hash | 1.5h | Medium |
| 3.4 | No SBOM generation | `tasks/repo_scan.py` | Generate CycloneDX/SPDX SBOM per engagement | 2h | Medium |
| 3.5 | No license compliance | `tasks/repo_scan.py` | Check licenses against policy (GPL, MIT, Apache) | 1.5h | Low |
| 3.6 | Only Semgrep | `tasks/repo_scan.py` | Add Bandit (Python), ESLint security plugins (JS), gosec (Go) | 3h | Medium |

---

## 4. Architecture

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 4.1 | Duplicated `_load_module` | `tasks/recon.py`, `scan.py`, `repo_scan.py`, `analyze.py` | Create `tasks/loader.py` with shared module loader | 1h | High |
| 4.2 | No circuit breaker for tools | `tools/tool_runner.py` | Add `CircuitBreaker` class: 3 failures → 5min cooldown | 2h | High |
| 4.3 | Sync AI calls block threads | `ai_explainer.py` | Convert to async with httpx.AsyncClient, 15s timeout, 2 retries | 2h | High |
| 4.4 | Load entire tool output in memory | `parsers/parser.py` | Yield findings as generator, batch insert every 50 | 2h | Medium |
| 4.5 | Hardcoded wordlist path | `orchestrator.py:261` | Use `Path(__file__).parent.parent / "wordlists"` or env var | 10m | High |
| 4.6 | No engagement event sourcing | - | Add `engagement_events` table for audit trail | 2h | Medium |
| 4.7 | No worker health endpoint | - | `GET /api/health/workers` querying Celery inspector stats | 1h | Medium |
| 4.8 | WebSocket per orchestrator | `orchestrator.py` | Singleton WebSocket publisher via Redis pub/sub | 2h | Low |
| 4.9 | No feature flags | - | Add feature flag system (env var + DB table) for gradual rollout | 3h | Low |
| 4.10 | Duplicate validation files | `src/lib/validation.ts`, `src/lib/requestValidation.ts` | Consolidate into single Zod-based validation module | 2h | Medium |

---

## 5. Code Quality & Maintainability

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 5.1 | Duplicate validation logic | `src/lib/validation.ts`, `requestValidation.ts` | Use Zod (already in deps) for type-safe validation | 2h | Medium |
| 5.2 | No TypeScript strict mode | `tsconfig.json` | Enable `strict: true`, fix resulting errors | 4h | High |
| 5.3 | Missing JSDoc on key functions | Worker modules | Add JSDoc for complex functions (orchestrator, intelligence_engine) | 2h | Medium |
| 5.4 | Inconsistent error handling | API routes | Standardize error response format: `{error, code, details}` | 3h | Medium |
| 5.5 | Magic numbers | Loop budget, rate limits | Extract to named constants in config files | 1h | Low |
| 5.6 | No linting for Python | - | Add `ruff` or `flake8` + pre-commit hook | 1h | Medium |
| 5.7 | Mixed connection patterns | Repositories | Standardize on connection pool usage, remove direct psycopg2.connect | 2h | High |

---

## 6. Performance

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 6.1 | N+1 query detection only logs | `src/lib/db.ts:67` | Add alerting or metrics export when N+1 detected | 1h | Medium |
| 6.2 | No query result caching | API routes | Add `withCache()` decorator for slow queries (findings list, engagement stats) | 2h | High |
| 6.3 | Large findings list loads all | `src/app/findings/page.tsx` | Implement virtual scrolling (react-window or react-virtualized) | 3h | High |
| 6.4 | WebSocket polls entire history | `src/lib/websocket.ts` | Use cursor-based pagination for event fetching | 2h | Medium |
| 6.5 | No database connection pooling config mismatch | `src/lib/db.ts`, `database/connection.py` | Align pool sizes between frontend and backend (20 vs 10) | 30m | Low |
| 6.6 | Heavy components not code-split | Dashboard | Lazy load `AttackPathGraph`, `ExecutionTimeline` (partially done) | 1h | Medium |

---

## 7. Security

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 7.1 | Password complexity not enforced | `src/lib/validation.ts` | Add regex: min 12 chars, uppercase, lowercase, number, special | 30m | High |
| 7.2 | No 2FA implementation | `src/lib/auth.ts:76` | References `two_factor_enabled` but no TOTP flow | 6h | High |
| 7.3 | Session timeout 30 days | `src/lib/auth.ts:103` | Reduce to 24h for security-sensitive app | 5m | High |
| 7.4 | No brute force protection | - | Add rate limiting on `/api/auth/signin` (already have redis-based limiter) | 1h | High |
| 7.5 | SQL injection via column allowlist bypass | `database/repositories/base.py:16` | Validate column names against schema, not allowlist | 1h | Medium |
| 7.6 | No input sanitization on evidence | `web_scanner.py` | Sanitize HTML/JS in evidence before DB storage | 1h | Medium |
| 7.7 | CORS middleware missing origin check | `src/middleware.ts` | Add origin validation for production | 30m | High |
| 7.8 | Secrets in logs | Various | Redact API keys, tokens from structured logs | 1h | Medium |

---

## 8. Testing

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 8.1 | No E2E test for engagement flow | `__tests__/e2e/` | Add Playwright test: create engagement → run scan → view findings | 4h | High |
| 8.2 | Missing integration tests | `__tests__/integration/` | Test API routes with real DB (test DB) | 3h | Medium |
| 8.3 | No frontend component tests | `src/components/` | Add Jest + React Testing Library for key components | 4h | Medium |
| 8.4 | Python tests have no coverage report | `argus-workers/tests/` | Add `pytest-cov`, set minimum 70% coverage | 1h | Medium |
| 8.5 | No contract testing (API ↔ Workers) | - | Add JSON schema validation for Celery job messages | 2h | Low |

---

## 9. Frontend Technical

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 9.1 | Missing ARIA labels | Interactive components | Add `aria-label`, `role`, `aria-live` where needed | 2h | Medium |
| 9.2 | No focus trap in modals | Dialog components | Implement focus trap for keyboard navigation | 1h | Medium |
| 9.3 | No error boundary | App root | Add React ErrorBoundary with fallback UI | 1h | High |
| 9.4 | State scattered across components | - | Consider Zustand or Jotai for global state (engagements, findings) | 4h | Low |
| 9.5 | No image optimization | - | Use Next.js `Image` component for all images | 2h | Low |
| 9.6 | Bundle size not monitored | - | Add `@next/bundle-analyzer` and size limits | 1h | Medium |

---

## 10. API & Backend

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 10.1 | No API versioning strategy | `src/app/api/` | Add `/api/v1/` prefix structure | 2h | Low |
| 10.2 | Inconsistent error responses | API routes | Standardize: `{error: string, code: string, details?: any}` | 3h | Medium |
| 10.3 | No request ID tracing | API routes | Add `X-Request-ID` header generation and propagation | 1h | High |
| 10.4 | Missing rate limit headers | `src/middleware.ts` | Add `X-RateLimit-Limit`, `X-RateLimit-Remaining` | 30m | Medium |
| 10.5 | No API documentation | - | Add OpenAPI/Swagger spec (optional) | 4h | Low |
| 10.6 | Idempotency key only for jobs | `src/lib/redis.ts:47` | Extend to POST/PUT API operations | 2h | Medium |

---

## 11. Database

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 11.1 | No index on findings.created_at | `db/schema.sql` | Add index for time-based queries | 10m | High |
| 11.2 | No index on findings.severity | `db/schema.sql` | Add index for severity filtering | 10m | High |
| 11.3 | JSONB columns not indexed | `db/schema.sql` | Add GIN indexes on `findings.evidence`, `engagements.authorized_scope` | 30m | Medium |
| 11.4 | No partitioning for large tables | `db/schema.sql` | Consider partitioning `findings` by created_at (quarterly) | 2h | Low |
| 11.5 | No foreign key cascade rules | `db/schema.sql` | Define ON DELETE behavior for engagements → findings | 30m | Medium |
| 11.6 | pgvector index missing | `db/schema.sql` | Add HNSW index for similarity search | 20m | Medium |

---

## 12. Documentation

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 12.1 | No API endpoint reference | `docs/` | Add API.md documenting all routes, params, responses | 3h | Medium |
| 12.2 | No contribution guide | `CONTRIBUTING.md` | Add dev setup, code style, PR process | 2h | Medium |
| 12.3 | Architecture doc outdated | `FINAL-ARCHITECTURE.md` | Keep in sync with code changes | Ongoing | Low |
| 12.4 | No changelog | `CHANGELOG.md` | Add versioned changelog | 1h | Low |
| 12.5 | Missing inline comments | Complex functions | Add JSDoc/docstring for orchestrator, intelligence_engine, attack_graph | 2h | Medium |

---

## Quick-Win Priority Order (Top 10)

1. **Portable wordlist path** (4.5) — 10m, fixes portability bug
2. **Session timeout reduction** (7.3) — 5m, security win
3. **Database indexes** (11.1, 11.2, 11.3) — 1h, performance win
4. **Centralize module loader** (4.1) — 1h, removes duplication
5. **Add error boundary** (9.3) — 1h, prevents white-screen crashes
6. **Request ID tracing** (10.3) — 1h, debugging win
7. **Consolidate validation files** (4.10, 5.1) — 2h, removes duplication
8. **Password complexity enforcement** (7.1) — 30m, security win
9. **Brute force protection** (7.4) — 1h, security win
10. **Circuit breaker for tools** (4.2) — 2h, prevents runaway failures

---

## Effort Summary

| Category | Total Effort |
|----------|--------------|
| UX | 18.5 hours |
| Website Scanning | ~23 hours |
| Repository Scanning | 16 hours |
| Architecture | 18.5 hours |
| Code Quality | 15 hours |
| Performance | 10.5 hours |
| Security | 12.5 hours |
| Testing | 14 hours |
| Frontend Technical | 14 hours |
| API & Backend | 14.5 hours |
| Database | 3 hours |
| Documentation | 10 hours |

**Total: ~160 hours** of improvement work across all categories.
