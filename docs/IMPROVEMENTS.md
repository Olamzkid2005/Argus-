# Argus Platform — Comprehensive Improvement Recommendations

> Deep codebase audit. No Docker/deployment suggestions. All actionable within current architecture.

---

## 1. User Experience (UX)

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 1.1 ✓ | **Command Palette** | `src/components/ui-custom/CommandPalette.tsx` | Wire up Cmd+K global shortcut with navigation (Dashboard, Findings, Engagements), actions (New Scan, Stop Scan), and search | 2h | **High** |
| 1.2 ✓ | **Bulk findings operations** | `src/app/findings/page.tsx` | Add checkboxes, bulk verify/delete/export, "Select All" with count badge | 3h | **High** |
| 1.3 ✓ | **Toast system fixes** | `src/components/ui/Toast.tsx:28` | Use `crypto.randomUUID()`, add max 5 toasts stack limit, ARIA live region, pause on hover | 1h | Medium |
| 1.4 ✓ | **URL history chips** | `src/app/engagements/page.tsx` | Store last 10 scanned URLs in localStorage, display as clickable chips with domain grouping | 45m | Medium |
| 1.5 ✓ | **Empty states** | Multiple pages | Create `<EmptyState>` component with illustration, action button, and helpful text for Dashboard, Findings, Engagements | 2h | **High** |
| 1.6 ✓ | **Keyboard shortcuts** | `src/hooks/` | Global `useKeyboardShortcuts`: Cmd+N (New Scan), E (Explain), V (Verify), ? (Help modal), Esc (Close panels) | 2h | Medium |
| 1.7 ✓ | **Charts theme-aware** | `src/app/engagements/page.tsx` | Create `useThemeColors()` hook reading CSS vars, update Recharts components | 1.5h | Low |
| 1.8 ✓ | **CVE/CWE interactive** | Finding detail components | Make CVE IDs clickable linking to NVD, add copy button, show CVSS vector | 45m | Low |
| 1.9 ✓ | **Onboarding flow** | `src/app/dashboard/` | Add first-time user detection, show guided tour with focus rings and tooltips | 3h | Medium |
| 1.10 ✓ | **Settings loading flash** | `src/app/engagements/page.tsx:80` | Add `settingsLoading` state with shimmer skeleton while fetching user preferences | 30m | **High** |
| 1.11 ✓ | **Scan progress** | `src/app/dashboard/page.tsx` | Enhance ScanStepTimeline with time estimates, current tool activity, and cancel per-phase | 2h | Medium |
| 1.12 ✓ | **Notification center** | `src/components/` | Add notification bell with unread count, persist in localStorage, link to recent events | 2.5h | Medium |
| 1.13 ✓ | **Mobile responsiveness** | Global CSS/Components | Audit touch targets (min 44px), fix table horizontal scroll, stack columns on mobile | 3h | Medium |
| 1.14 ✓ | **Finding detail tabs** | `src/app/findings/[id]/page.tsx` | Add tabbed view (Overview, Evidence, Remediation, Similar), add "Copy curl" for PoC | 2.5h | Medium |
| 1.15 ✓ | **Quick scan templates** | `src/app/engagements/page.tsx` | Add preset templates (Quick, Full, Compliance, API-only) with pre-filled settings | 1.5h | Low |

### New UX Improvements Explained:

**1.1 Command Palette (HIGH PRIORITY)**
- cmdk is already installed and `CommandDialog` component exists
- Needs global Cmd+K (Ctrl+K) keyboard listener in `layout.tsx` or `ClientLayout.tsx`
- Include: Navigation (Go to Dashboard, Findings, Engagements, Settings), Actions (New Scan, Stop Scan, Export Report), Search (Find findings by ID or type)
- Show keyboard hints next to each command

**1.2 Bulk Findings Operations (HIGH PRIORITY)**
- Add checkbox column to findings table
- Header checkbox for "Select All" with indeterminate state
- Floating action bar appears when items selected: "3 selected" with Verify, Delete, Export buttons
- Persist selection across pagination/filtering

**1.3 Toast System Fixes (MEDIUM PRIORITY)**
```typescript
// Current (line 28): const id = Math.random().toString(36).substring(7);
// Fixed: const id = crypto.randomUUID();
```
- Add max 5 toasts with queue system
- Add `role="alert"` and `aria-live="polite"` for screen readers
- Pause auto-dismiss timer on hover
- Add progress bar animation using CSS `@keyframes`

**1.5 Empty States (HIGH PRIORITY)**
- Create reusable `<EmptyState>` component:
  - Icon/illustration slot
  - Title and description
  - Primary action button
  - Secondary link (e.g., "Learn more")
- Apply to: Dashboard (no engagements), Findings (no results), Engagements (empty list)

**1.6 Keyboard Shortcuts (MEDIUM PRIORITY)**
- Create `src/hooks/useKeyboardShortcuts.ts`:
  - `Cmd+K`: Open command palette
  - `Cmd+N`: Create new engagement (when on engagements page)
  - `E`: Explain selected finding (when finding selected)
  - `V`: Verify selected finding
  - `?`: Show keyboard shortcuts help modal
  - `Esc`: Close modals/panels
- Show shortcut hints in tooltips and menus

**1.10 Settings Loading Flash (HIGH PRIORITY)**
- Current code (line 80-93) fetches settings without loading state
- Add `settingsLoading` state, show shimmer/skeleton while loading
- Prevent scan aggressiveness from flashing between default and user setting

**1.14 Finding Detail Tabs (MEDIUM PRIORITY)**
- Currently findings detail is in a side panel
- Add tabs: Overview (current), Evidence (technical details), Remediation (AI-generated fix steps), Similar (related findings)
- Add "Copy as curl" button for easy PoC reproduction

---

## 2. Website Scanning

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 2.1 ✓ | **Modern vulnerability checks** | `tools/web_scanner.py:34` | Add GraphQL introspection, JWT alg confusion, prototype pollution, cache poisoning, HTTP smuggling, DOM XSS, OpenAPI discovery | ~10h | High |
| 2.2 ✓ | **Differential analysis** | `tools/web_scanner.py` | `differential_check()`: baseline→payload→compare hash/reflectivity (~60% FP reduction) | 3h | High |
| 2.3 ✓ | **WAF detection** | `tools/web_scanner.py` | `detect_waf()`: check CF-RAY, x-mod-security, blocked strings. Tag findings `waf_interference: true` | 2h | High |
| 2.4 ✓ | **Parameter discovery & fuzzing** | `tools/web_scanner.py` | Feed discovered forms/params from katana crawl into injection tests | 2h | Medium |
| 2.5 ✓ | **Time-based detection** | `tools/web_scanner.py` | Add SLEEP payloads for SQL/Command injection timing attacks | 1.5h | Medium |
| 2.6 ✓ | **SSL verification** | `tools/web_scanner.py` | Remove `verify=False`, use proper SSL verification with option to disable per-target | 30m | High |
| 2.7 ✓ | **Per-endpoint rate limiting** | `tools/web_scanner.py` | Per-endpoint rate limiting (currently only global) | 1h | Medium |
| 2.8 ✓ | **Response analysis** | `tools/web_scanner.py` | Parse HTTP status codes, content-type, response size for fingerprinting | 1h | Low |

---

## 3. Repository Scanning

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 3.1 ✓ | **Dependency scanning (SCA)** | `tasks/repo_scan.py` | Add npm audit, pip-audit, govulncheck, Maven Central checks. Store as `DEPENDENCY_VULNERABILITY` | 6h | High |
| 3.2 ✓ | **Git history secret scan** | `tasks/repo_scan.py` | Run `git log --all --patch` for committed secrets (trufflehog-style) | 2h | High |
| 3.3 ✓ | **Commit blame timeline** | `tasks/repo_scan.py` | `git blame` findings to show introduced_at, author, commit hash | 1.5h | Medium |
| 3.4 ✓ | **SBOM generation** | `tasks/repo_scan.py` | Generate CycloneDX/SPDX SBOM per engagement | 2h | Medium |
| 3.5 ✓ | **License compliance** | `tasks/repo_scan.py` | Check licenses against policy (GPL, MIT, Apache) | 1.5h | Low |
| 3.6 ✓ | **More SAST tools** | `tasks/repo_scan.py` | Add Bandit (Python), ESLint security plugins (JS), gosec (Go) | 3h | Medium |

---

## 4. Architecture

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 4.1 ✓ | **Shared module loader** | `tasks/recon.py`, `scan.py`, `repo_scan.py`, `analyze.py` | Create `tasks/loader.py` with shared module loader | 1h | High |
| 4.2 ✓ | **Circuit breaker for tools** | `tools/tool_runner.py` | Add `CircuitBreaker` class: 3 failures → 5min cooldown | 2h | High |
| 4.3 ✓ | **Async AI calls** | `ai_explainer.py` | Convert to async with httpx.AsyncClient, 15s timeout, 2 retries | 2h | High |
| 4.4 ✓ | **Generator-based parsing** | `parsers/parser.py` | Yield findings as generator, batch insert every 50 | 2h | Medium |
| 4.5 ✓ | **Configurable wordlist path** | `orchestrator.py:261` | Use `Path(__file__).parent.parent / "wordlists"` or env var | 10m | High |
| 4.6 ✓ | **Engagement event sourcing** | - | Add `engagement_events` table for audit trail | 2h | Medium |
| 4.7 ✓ | **Worker health endpoint** | - | `GET /api/health/workers` querying Celery inspector stats | 1h | Medium |
| 4.8 ✓ | **Singleton WebSocket publisher** | `orchestrator.py` | Singleton WebSocket publisher via Redis pub/sub | 2h | Low |
| 4.9 ✓ | **Feature flags system** | - | Add feature flag system (env var + DB table) for gradual rollout | 3h | Low |
| 4.10 ✓ | **Consolidated Zod validation** | `src/lib/validation.ts`, `src/lib/requestValidation.ts` | Consolidate into single Zod-based validation module | 2h | Medium |

---

## 5. Code Quality & Maintainability

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 5.1 ✓ | **Zod-based validation** | `src/lib/validation.ts`, `requestValidation.ts` | Use Zod (already in deps) for type-safe validation | 2h | Medium |
| 5.2 ✓ | **TypeScript strict mode** | `tsconfig.json` | Enable `strict: true`, fix resulting errors | 4h | High |
| 5.3 ✓ | **JSDoc on worker functions** | Worker modules | Add JSDoc for complex functions (orchestrator, intelligence_engine) | 2h | Medium |
| 5.4 ✓ | **Standardized error responses** | API routes | Standardize error response format: `{error, code, details}` | 3h | Medium |
| 5.5 ✓ | **Named constants** | Loop budget, rate limits | Extract to named constants in config files | 1h | Low |
| 5.6 ✓ | **Ruff + pre-commit hooks** | - | Add `ruff` or `flake8` + pre-commit hook | 1h | Medium |
| 5.7 ✓ | **Connection pool standardization** | Repositories | Standardize on connection pool usage, remove direct psycopg2.connect | 2h | High |

---

## 6. Performance

| # | Issue | File | Fix | Effort | Priority |
|---|-------|------|-----|--------|----------|
| 6.1 | N+1 query detection only logs | `src/lib/db.ts:67` | Add alerting or metrics export when N+1 detected | 1h | Medium |
| 6.2 | No query result caching | API routes | Add `withCache()` decorator for slow queries (findings list, engagement stats) | 2h | High |
| 6.3 | Large findings list loads all | `src/app/findings/page.tsx` | Implement virtual scrolling (react-window or react-virtualized) | 3h | High |
| 6.4 | WebSocket polls entire history | `src/lib/websocket.ts` | Use cursor-based pagination for event fetching | 2h | Medium |
| 6.5 | No database connection pooling config mismatch | `src/lib/db.ts`, `database/connection.py` | Align pool sizes between frontend and backend (20 vs 10) | 30m | Low |
| 6.6 | Heavy components not code-split | Dashboard | Lazy load `AttackPathGraph`, `ExecutionTimeline` (partially done) ✓ | 1h | Medium |

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
| 9.3 | No error boundary | App root | Add React ErrorBoundary with fallback UI ✓ | 1h | High |
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
5. **Add error boundary** (9.3) — 1h, prevents white-screen crashes ✓ *DONE*
6. **Request ID tracing** (10.3) — 1h, debugging win
7. **Consolidate validation files** (4.10, 5.1) — 2h, removes duplication
8. **Password complexity enforcement** (7.1) — 30m, security win
9. **Brute force protection** (7.4) — 1h, security win
10. **Circuit breaker for tools** (4.2) — 2h, prevents runaway failures

### New UX Quick-Wins:
- **Settings loading flash fix** (1.10) — 30m, eliminates UI jitter
- **Toast ID fix** (1.3) — 1h, prevents duplicate toasts
- **URL history chips** (1.4) — 45m, improves scan re-execution UX

---

## Effort Summary

| Category | Total Effort |
|----------|--------------|
| UX | ~25 hours |
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

**Total: ~166 hours** of improvement work across all categories.

---

## Implementation Notes

### ✓ Completed Items (from old UX section):
- **1.7** ScannerActivityPanel visual stepper — Already implemented with ScanStepTimeline component
- **9.3** Error boundary — Already implemented as `src/components/ErrorBoundary.tsx`

### Key UX Design Principles for Argus:
1. **Progressive Disclosure**: Show basic info first, details on demand (findings side panel already does this well)
2. **Immediate Feedback**: All actions should show immediate visual feedback (toasts, loading states)
3. **Keyboard-First**: Power users should never need the mouse (implement command palette + shortcuts)
4. **Theme Consistency**: Charts, icons, and UI elements should respect light/dark theme
5. **Graceful Empty States**: Never show blank pages — always guide users to next action
6. **Scan Transparency**: Users should always know what's happening during a scan (activity panel helps, enhance with time estimates)

### Command Palette Implementation Sketch:
```typescript
// src/hooks/useCommandPalette.ts
export function useCommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((open) => !open);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);
  
  const commands = [
    { category: "Navigation", items: [
      { label: "Dashboard", shortcut: "G D", action: () => router.push("/dashboard") },
      { label: "Findings", shortcut: "G F", action: () => router.push("/findings") },
      { label: "Engagements", shortcut: "G E", action: () => router.push("/engagements") },
    ]},
    { category: "Actions", items: [
      { label: "New Scan", shortcut: "Cmd+N", action: () => router.push("/engagements") },
      { label: "Stop Scan", shortcut: "", action: () => {/* stop logic */} },
    ]},
  ];
  
  return { open, setOpen, commands };
}
```
