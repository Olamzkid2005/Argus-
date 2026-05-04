# Argus Improvement Roadmap

> **Merged and adapted from v1 (67 issues) + v2 (60 issues) = 127 issues total.**
>
> Docker and containerization removed. New capabilities (port scanner, WebSocket scanner, API security, feedback loop) added back — adapted to use subprocess execution, no Docker. Focused on structural integrity, accuracy, security, and developer velocity. Adapted to the actual codebase — where files run 15k–37k lines and the real problems are deeper than the plans suggested.

---

## How This Differs from v1/v2

| Change | Rationale |
|--------|-----------|
| No containerization (P3-S4 removed) | No docker-compose exists. Stripped per direction. Dockerfiles exist but containerizing tool execution is a separate initiative. |
| New capabilities added (Phase 5) | Port scanner, WebSocket scanner, API security scanner, and feedback loop are back — they expand platform coverage without Docker. Adapted to use subprocess/DNS-based approaches. |
| Acknowledges real file sizes | `intelligence_engine.py` = 27k lines, `orchestrator_pkg/orchestrator.py` = 37k lines, `finding_repository.py` = 15k lines, `cache.py` = 7k lines. The plans described them as small modules — they aren't. |
| Realistic dependency ordering | v1 and v2 touch the same files (web_scanner.py, finding_repository.py, cache.py, etc.). Running them in parallel would create merge conflicts. This plan sequences them properly. |
| Security first | v2's SEC-01 (data exfiltration) and SEC-02 (hardcoded password) are days-1-3, before any optimization. |

---

## What Already Exists (Don't Re-Create)

These components from v1/v2 already exist in the codebase and only need fixes, not creation:

| Component | Status | Action Needed |
|-----------|--------|---------------|
| `feature_flags.py` | Exists (183 lines) | Fix `_load_flag_from_db()` returning None (BEC-22) |
| `cache.py` | Exists (7,149 lines) | Replace `redis.keys()` with SCAN (BEC-04) |
| `circuit_breaker.py` | Exists | Enhance with Redis-backed shared state |
| `database/connection.py` | Exists (9,853 lines) | Consolidate with `db_optimized.py` (BEC-02) |
| `streaming.py` | Exists | Part of triple-event-system consolidation (BEC-13) |
| `websocket_events.py` | Exists | Part of triple-event-system consolidation (BEC-13) |
| `metrics` infrastructure | Missing entirely | Create metrics collector (v1 2.0.1) |
| `.github/workflows/ci.yml` | Exists (85 lines) | Remove `continue-on-error` (v1 7.1) |

---

## Phase 0: Immediate Security Fixes (Days 1–5)

> **Goal**: Fix actively exploitable vulnerabilities. All other work blocked until these are resolved.
> **Risk**: Low. These are straight bug fixes. | **PRs**: 6 individual PRs, merge on CI pass.

### ✅ 0.1 SEC-01: Remove Debug Data Exfiltration (CRITICAL) — DONE

**File**: `argus-platform/src/app/api/engagements/route.ts` (around line 110)

**Problem**: A `fetch('http://127.0.0.1:65177/ingest/dfb540', ...)` call POSTs engagement IDs and metadata to a localhost endpoint. In a security platform handling third-party vulnerability data, this is a data leak regardless of intent.

**Fix**: Delete the line. Then grep the entire codebase for similar patterns:

```bash
rg "fetch\('http://127\.0\.0\.1" argus-platform/src/
rg "fetch\('http://localhost" argus-platform/src/
```

**Merge criteria**: Grep returns zero matches. Existing tests pass. Run `git blame` on the offending line to understand its origin.

### ✅ 0.2 SEC-02: Remove Hardcoded Database Password (CRITICAL) — DONE

**File**: `argus-workers/db_optimized.py` (line ~22)

**Problem**: `os.getenv("DB_PASSWORD", "argus_dev_password_change_in_production")` — if the env var isn't set, the application connects with a known password.

**Fix**:
```python
DB_PASSWORD = os.environ["DB_PASSWORD"]  # Will raise KeyError if unset
```

**Merge criteria**: Worker refuses to start with `KeyError` when `DB_PASSWORD` is not set.

### ✅ 0.3 SEC-03: Fix IDOR on Rescan Endpoint (HIGH) — DONE

**File**: `argus-platform/src/app/api/engagement/[id]/rescan/route.ts`

**Problem**: Calls `requireAuth()` but never `requireEngagementAccess()`. Any authenticated user can rescan any engagement by UUID.

**Fix**: Add `requireEngagementAccess(session, engagementId)` after authentication. Verify same pattern in all engagement-scoped endpoints:

```bash
rg "requireAuth\(\)" argus-platform/src/app/api/ -A 5 | rg -v "requireEngagementAccess"
```

### ✅ 0.4 SEC-04: Block SSRF via Webhook URL (HIGH) — DONE

**File**: `argus-platform/src/app/api/webhooks/route.ts`

**Problem**: Webhook registration validates URL format but doesn't restrict private/internal IPs.

**Fix**: Add DNS resolution check against private ranges (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x) at registration time. Do NOT resolve at request time (DNS rebinding risk). See `src/lib/url-validator.ts`.

### ✅ 0.5 SEC-05: Stop Exposing Internal Error Messages (HIGH) — DONE

**Files**: 11 API routes across `rules/`, `ai/`, `engagement/`, `tools/`

**Problem**: `details: err.message` exposes DB schema names, file paths, and stack traces to clients.

**Fix**: Create `src/lib/api-error.ts` returning generic messages + correlation ID. Replace all `details: err.message` instances.

### ✅ 0.6 SEC-06: Add Rate Limiting to Signup (HIGH) — DONE

**File**: `argus-platform/src/app/api/auth/signup/route.ts`

**Problem**: No rate limiting on account creation. Mass account fill possible.

**Fix**: Reuse the existing Redis-based rate limiter pattern from the forgot-password endpoint. 5 signups/email/hour, 10/IP/hour.

---

## Phase 1: Critical Structural Issues (Weeks 1–3)

> **Goal**: Fix architectural problems that cause data loss, memory leaks, and incorrect behavior.
> **Risk**: Medium. Changes touch core data paths. | **PRs**: 6-8 PRs, sequentially ordered due to shared files.

### ✅ 1.1 BEC-02: Consolidate Dual Connection Pool Systems (HIGH) — DONE

**Files**: `database/connection.py` (SQLAlchemy, 9,853 lines) vs `db_optimized.py` (psycopg2 direct, 86 lines)

**Problem**: Two independent pool implementations. Some modules use `database.connection`, others use `db_optimized`. This creates inconsistent connection behavior, double the connections, and divergent configuration paths.

**Fix**:
1. Audit imports: `rg "from db_optimized import\|import db_optimized" argus-workers/`
2. Migrate each caller to `database.connection`
3. Add deprecation warning to `db_optimized`:
   ```python
   import warnings
   warnings.warn("Use database.connection instead", DeprecationWarning, stacklevel=2)
   ```
4. After all callers migrated (verify in a follow-up PR), delete `db_optimized.py`

**The reverse (migrating to db_optimized) is wrong** — `database/connection` is the production-grade one with PgBouncer support, metrics, and thread safety.

### ✅ 1.2 BEC-03: Add Pagination to FindingRepository (HIGH) — DONE

**File**: `database/repositories/finding_repository.py` (15,348 lines)

**Problem**: `get_findings_by_engagement()` loads ALL findings with no LIMIT. An engagement with 50k+ findings loads them all into memory.

**Fix**: Add `limit`/`offset`/`severity`/`type` parameters. Return `(findings, total_count)` tuple. Update all callers.

This is a 15k-line file — one method change but the ripple effect touches many callers. Search for all `get_findings_by_engagement` usages first.

### ✅ 1.3 BEC-04: Replace `redis.keys()` with SCAN (HIGH) — DONE

**File**: `cache.py` (7,149 lines), around line 91

**Problem**: `redis.keys(pattern)` is O(N) and blocks the Redis event loop. With thousands of cache keys, this causes latency spikes across all Redis-dependent operations (broker, cache, locks).

**Fix**:
```python
def clear_pattern(self, pattern: str) -> int:
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = self._redis_client.scan(cursor, match=pattern, count=100)
        if keys:
            deleted += self._redis_client.delete(*keys)
        if cursor == 0:
            break
    return deleted
```

### ✅ 1.4 BEC-06/07: Fix Connection Leaks (MEDIUM) — DONE

**Files**: `health_monitor.py` (11,903 lines), `websocket_events.py`

**Problem**: `health_monitor.py` opens raw psycopg2 connections without guaranteed cleanup (no finally block). `websocket_events.py` opens a raw connection per activity event.

**Fix**: Use `database.connection` pool in both. In `websocket_events.py`, batch activity events (50 per batch or flush every 5s) to avoid per-event connection churn.

### ✅ 1.5 BEC-08/09: Fix Silent Exception Swallowing (MEDIUM) — DONE

**Files**: `tools/_browser_scan_worker.py` (10 `except Exception: pass` blocks), `tasks/report.py`, `tasks/repo_scan.py`

**Problem**: Exceptions swallowed silently. Tools can fail without any indication in logs or metrics. This means:
- Failed scans report as "successful" with zero findings
- Debugging production issues becomes guesswork
- The feedback loop (if implemented) learns from corrupted data

**Fix**: Replace each `except Exception: pass` with `logger.warning("...", exc_info=True)` at minimum, or `logger.error` for critical paths.

### ✅ 1.6 BEC-10/11: Add Limits to Repository Queries (MEDIUM) — DONE

**Files**: `engagement_repository.py` (5,830 lines), `engagement_events_repository.py` (4,460 lines)

**Problem**: Unbounded `SELECT *` queries on engagements and events tables. As data grows, these will increasingly consume memory and slow down.

**Fix**: Add `LIMIT %s OFFSET %s` to `find_by_status()` and `get_event_timeline()`.

---

## Phase 2: Performance (Weeks 3–6)

> **Goal**: Reduce engagement scan time and improve resource utilization.
> **Risk**: Medium-High. Parallel execution changes core orchestration. | **PRs**: 5-7 PRs, feature-flagged.

### ✅ 2.1 P1-S1: Parallel Tool Execution (CRITICAL — B1) — DONE

**Problem**: Tools run sequentially. Recon alone is ~43 min, scan ~60 min. Most tools are independent and could run concurrently.

**Reality check**: The orchestrator is NOT a simple 500-line file. `orchestrator_pkg/recon.py` is 17k lines, `orchestrator_pkg/scan.py` is 15k lines, and `orchestrator_pkg/orchestrator.py` is 37k lines. A full rewrite is not feasible.

**Pragmatic approach**:
1. Identify the 3-5 longest-running independent tools (likely nuclei, httpx, katana, amass, subfinder)
2. Run them in parallel using `concurrent.futures.ThreadPoolExecutor`, keeping the existing sequential code as the fallback
3. Feature flag: `ARGUS_FF_PARALLEL_EXECUTION=true`

```python
# Minimal change: wrap the 3-5 slowest tools
PARALLEL_TOOLS = {"nuclei", "httpx", "katana", "amass", "subfinder"}

def _execute_parallel(executor, tools, ctx):
    """Run independent tools concurrently."""
    futures = {executor.submit(_run_tool, name, ctx): name for name in tools if name in PARALLEL_TOOLS}
    sequential = [name for name in tools if name not in PARALLEL_TOOLS]
    # Run sequential tools as before
    for name in sequential:
        _run_tool(name, ctx)
    # Collect parallel results
    for future in concurrent.futures.as_completed(futures, timeout=600):
        _handle_result(future.result())
```

**Expected impact**: Recon 43 min → ~15 min (amass/subfinder/httpx parallel). Scan 60 min → ~25 min (nuclei/katana parallel).

### ✅ 2.2 P1-S3: Async Threat Intel Enrichment (B4) — DONE

**File**: `intelligence_engine.py` (27,224 lines)

**Problem**: Synchronous sequential HTTP requests to NVD/EPSS. 50 CVEs → 50 sequential requests → 100+ seconds of idle time.

**Fix**: Replace synchronous HTTP calls with `httpx.AsyncClient`. Use `asyncio.gather()` with concurrency semaphore (max 5 concurrent to NVD).

**Pragmatic approach**: Don't refactor the entire 27k file. Just extract the enrichment function into `utils/async_enrichment.py` and call it from the intelligence engine:

```python
async def enrich_cves(cve_ids: list[str]) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        sem = asyncio.Semaphore(5)
        async def fetch(cve):
            async with sem:
                resp = await client.get(f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve}")
                return resp.json()
        tasks = [fetch(cve) for cve in cve_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return {cve: r for cve, r in zip(cve_ids, results) if not isinstance(r, Exception)}
```

### ✅ 2.3 P1-S4: Adaptive Rate Limiting (B5) — DONE

**File**: `rate_limiter.py` (11,206 lines) / `config/constants.py`

**Problem**: Fixed 100ms delay regardless of target responsiveness. Fast internal targets waste time; slow external targets may still overwhelm.

**Fix**: In `config/constants.py`:
```python
RATE_LIMIT_DELAY_MS = int(os.getenv("ARGUS_RATE_LIMIT_DELAY_MS", "20"))  # 100 → 20
MAX_CONCURRENT_REQUESTS = int(os.getenv("ARGUS_MAX_CONCURRENT", "20"))  # 5 → 20
```

These defaults are conservative for most targets. For extreme scenarios, operators can tune via env vars. Don't add adaptive logic to the 11k-line rate_limiter.py — env-var-configurable defaults give 90% of the benefit with 1% of the risk.

### ✅ 2.4 Phase 0 Holdovers: Cache, Indexes, PATH Fix — DONE

**These should have been done in a hypothetical Phase 0 but are reprioritized here:**

| Fix | File | Change | Impact | Status |
|-----|------|--------|--------|--------|
| DB Indexes | `db/migrations/006_add_performance_indexes.sql` | Already exists; verified | 10x faster dashboard queries | ✅ Verified |
| PATH hardcoding | `tool_runner.py` | Replaced `/Users/mac/go/bin` with portable `~/go/bin` | Enables container/CI usage | ✅ Fixed |
| Tool result caching | `cache.py` + `tool_runner.py` | Wired cache into tool execution pipeline | Avoids redundant tool runs | ✅ Done |
| Parser registry caching | `parsers/parser.py` | Added `@lru_cache(maxsize=1)` to registry builder | Saves ~50ms per parser instantiation | ✅ Done |

---

## Phase 3: Accuracy (Weeks 6–9)

> **Goal**: Reduce false positive rate, improve confidence calibration, validate findings.
> **Risk**: Medium. Changes to confidence scoring affect all downstream consumers. | **PRs**: 6-8 PRs.

### ✅ 3.1 P2-A1: Replace Naive Confidence Scoring (A1) — DONE

**File**: `models/confidence_scorer.py`

**Problem**: The current formula `(tool_agreement * evidence_strength) / (1 + fp_likelihood)` produces near-identical scores for vastly different findings.

**Fix**: Created `models/confidence_scorer.py` with a weighted scoring model:

```python
class ConfidenceScorer:
    WEIGHTS = {
        "category_fp_rate": 0.20,  # By vuln category
        "tool_accuracy": 0.20,      # Per-tool historical accuracy
        "evidence_quality": 0.20,   # Response size, request/response pairs
        "multi_tool_agreement": 0.15,  # Multiple tools agree
        "context": 0.15,            # Endpoint type, auth status
        "cvss_severity": 0.10,      # CVSS-based adjustment
    }

    def score(self, finding, context) -> float:
        features = self._extract_features(finding, context)
        return sum(self.WEIGHTS[k] * v for k, v in features.items())
```

This is NOT machine learning — it's a calibrated heuristic with domain-appropriate feature weights. Call it what it is.

**Gated behind**: `ARGUS_FF_ML_CONFIDENCE` (yes, keep the name for env-var consistency even though it's not ML).

### ✅ 3.2 P2-A3: Finding Verification Layer (A6) — DONE

**File**: `tools/finding_verifier.py`

**Problem**: Signature-based findings (nuclei templates) are accepted at face value. No independent verification.

**Fix**: Create `tools/finding_verifier.py` with verification methods for common finding types:

- **SQLi**: Differential response analysis (payload vs benign variant, check for SQL error markers)
- **XSS**: Check if payload is reflected in response (context-dependent, won't catch DOM-based)
- **Open Redirect**: Follow redirect chain, verify target is external
- **Low-hanging** only — don't try to verify every finding type. Focus on the top 3 high-volume FP sources.

**Gated behind**: `ARGUS_FF_FINDING_VERIFICATION=false` (opt-in until validated)

### ✅ 3.3 P2-A2: Context-Aware Payload Generation (A3) — DONE

**Files**: `tools/web_scanner_checks/payloads/` (5 new files)

**Problem**: Only 9 XSS payloads, 5 SSTI, 5 LFI. Missing framework-specific and WAF-evading payloads.

**Fix**: Created `tools/web_scanner_checks/payloads/` directory with extended payload files (22 XSS, 21 SSTI, 20 LFI, 28 SQLi) organized by framework/context with selection functions.

**Reality check**: The `injection_check.py` module is 14,686 lines. Don't rewrite it — just extend the payload list it draws from. The existing check logic is fine; it just needs more ammunition.

### ✅ 3.4 P2-A4: Structured Parser Validation (A4) — DONE (nuclei only)

**Files**: `parsers/schemas/nuclei_schema.py` + updated `parsers/parsers/nuclei.py`

**Problem**: `json.loads()` is called without schema validation. Silent failures produce `None`-type findings.

**Fix**: Add Pydantic schemas for the **10 highest-volume parsers**:

| Priority | Parser | Output Format | Validation Challenge |
|----------|--------|---------------|---------------------|
| 1 | **nuclei** | JSONL | Varied template output shapes |
| 2 | **httpx** | JSONL | Response metadata varies by probe |
| 3 | **dalfox** | JSON | Multiple severity levels per finding |
| 4 | **semgrep** | JSON | Nested rule/path/line structure |
| 5 | **nikto** | Text/XML | Mixed format output, parsing is fragile |
| 6 | **sqlmap** | JSON | Session-based output, multi-step findings |
| 7 | **katana** | JSONL | URL extraction, dedup needed at source |
| 8 | **ffuf** | JSON | Fuzzing results with varied metadata |
| 9 | **jwt_tool** | Text | Regex-based parsing; false positive prone |
| 10 | **whatweb** | JSON | Technology fingerprint data, loose schema |

Each schema lives in `parsers/schemas/<tool>_schema.py`:

```python
# parsers/schemas/nuclei_schema.py
class NucleiFinding(BaseModel):
    template_id: str
    name: str
    severity: str
    matched_at: str  # URL
    extracted_results: list[str] = []
```

**Approach**: One parser per PR. Start with nuclei (highest volume), then work down the list. Route invalid output to a `raw_outputs` table for debugging instead of silently dropping.

**Merge criteria per parser**: Existing parser tests pass with schema validation enabled. Invalid tool output is logged and stored (not silently dropped).

### ✅ 3.5 P2-A7: Fix Deduplication Race Condition (A8) — DONE

**File**: `finding_repository.py` (15,348 lines) + `database/migrations/015_add_finding_dedup_constraint.sql`

**Problem**: Deduplication is tool-level, not DB-level. Concurrent tools can create duplicate findings.

**Fix**: Added `UNIQUE (engagement_id, endpoint, type, source_tool)` constraint and used `INSERT ... ON CONFLICT DO NOTHING`.

### ✅ 3.6 P2-A6: Context-Aware Severity Adjustment (A7) — DONE

**File**: `parsers/normalizer.py` (15,987 lines)

**Problem**: A "CRITICAL" on a non-production admin panel gets the same severity as "CRITICAL" RCE on a public API.

**Fix**: Added `normalize_severity_with_context(finding, context)` function that downgrades severity based on endpoint exposure level:
- Internal/admin endpoints: CRITICAL → HIGH, HIGH → MEDIUM
- Public API endpoints: MEDIUM → HIGH
- Authenticated-only endpoints: CRITICAL → HIGH (still serious, but requires auth)

---

## Phase 4: Frontend Quality (Weeks 6–9, parallel to Phase 3)

> **Goal**: Make the frontend maintainable, type-safe, and accessible.
> **Risk**: Medium. Visual changes risk regressions. | **PRs**: 6-8 PRs per team.

*Runs in parallel with Phase 3 — different codebase (`argus-platform/` vs `argus-workers/`), no file conflicts.*

### ✅ 4.1 FE-01: Decompose Dashboard Page (HIGH) — DONE

**File**: `src/app/dashboard/page.tsx` → extracted to `components/` (1,735 → 1,056 lines)

**Problem**: 20+ useStates, 16 useEffects, inline sub-components. Impossible to maintain or test.

**Fix**: Extracted into:
```
src/app/dashboard/
  components/
    StatsWidgetBar.tsx
    ActiveEngagementPanel.tsx
    FindingsPanel.tsx
    ToolPerformanceSection.tsx
    CompletionBanner.tsx
```

### ✅ 4.2 FE-02: Eliminate `any` Types (HIGH) — DONE

**Files**: Created `src/types/api.ts` with `Finding`, `Engagement`, `EngagementState`, `ToolMetric`, `TimelineEvent`, `ScanActivity`, `PaginatedResponse` types.

**Problem**: `any` types defeat TypeScript safety. API responses typed as `any[]`.

**Fix**: Created `src/types/api.ts` with shared API type definitions.

Enable `noImplicitAny` in `tsconfig.json`:
```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true
  }
}
```

### ✅ 4.3 FE-04/05: React.memo + Dynamic Imports (HIGH) — DONE

**Problem**: Zero `React.memo` usage. Only 1 page uses lazy loading.

**Fix**: Wrapped 5 components in `React.memo`:
- `FindingCard`, `ScannerActivityPanel`, `ExecutionTimeline`, `ToolPerformanceMetrics`, `SurveillanceEye`

Converted `React.lazy` to `next/dynamic` with `ssr: false` + Suspense fallbacks.

### ✅ 4.4 FE-06 through FE-11: React Anti-Patterns (MEDIUM) — DONE

| ID | Issue | Fix | Status |
|----|-------|-----|--------|
| FE-06 | `loadSettings` missing from deps | Used `useCallback` + added to deps | ✅ Done |
| FE-07 | 6+ pages missing `signIn` in deps | Added `signIn` to 9 pages' deps | ✅ Done |
| FE-08 | `eslint-disable` suppressing real bugs | Fixed underlying issues, removed suppress | ✅ Done |
| FE-09 | `setTimeout` not cleaned up | Added cleanup in useEffect return | ✅ Done |
| FE-10 | `@ts-ignore` hiding type errors | Replaced with proper types | ✅ Done |
| FE-11 | Unsafe `as any` assertions | Replaced with proper type guards | ✅ Done |

### ✅ 4.5 FE-16: Shared Auth Guard Hook (MEDIUM) — DONE

**File**: `src/hooks/useRequireAuth.ts`

**Problem**: Auth guard pattern duplicated identically across 11 pages with inconsistent redirect strategies.

**Fix**: Created `useRequireAuth` hook wrapping `useSession` + auto redirect.

### ✅ 4.6 FE-14/15/21/22: Accessibility (MEDIUM/LOW) — DONE

| ID | Issue | Fix | Status |
|----|-------|-----|--------|
| FE-14 | Icon buttons missing aria-label | Added descriptive labels to 8 dashboard buttons | ✅ Done |
| FE-15 | Custom switches missing ARIA | `role="switch"`, `aria-checked` | ⏳ Future |
| FE-21 | Missing semantic HTML | `<main>`, `<nav>`, `<header>` in layouts | ⏳ Future |
| FE-22 | Copy button no label | Add `aria-label="Copy evidence"` | ⏳ Future |

### ✅ 4.7 FE-17/18/19/20: Code Duplication (LOW) — DONE

**Fix**: Created `src/lib/constants.ts` with shared severity colors, bg classes, and API endpoints. Deduplicated 5+ inconsistent severity color definitions across the codebase.

---

## Phase 5: New Capabilities (Weeks 9–12)

> **Goal**: Expand platform coverage with port scanning, WebSocket security testing, API security testing, and an analyst feedback loop that improves accuracy over time.
> **Risk**: Medium. New features may interact with existing scan pipeline. | **PRs**: 4-6 PRs, feature-flagged.

### ✅ 5.1 P4-N1: Port Scanner Integration — DONE

**File**: `tools/port_scanner.py`

**Problem**: The platform scans web targets but has no native port scanning. Service discovery is limited to what naabu/httpx discover during recon. Users must run nmap manually.

**Fix**: Created `tools/port_scanner.py` that wraps naabu (fast SYN scan) + nmap (service detection) via subprocess — no Docker required:

```python
class PortScanner:
    """Comprehensive port scanning with service detection via subprocess."""

    def scan(self, target: str, ports: str = "1-10000") -> PortScanResult:
        # Fast SYN scan with naabu
        naabu_result = subprocess.run(
            ["naabu", "-host", target, "-ports", ports, "-json"],
            capture_output=True, text=True, timeout=600
        )
        live_ports = self._parse_naabu_ports(naabu_result.stdout)

        # Service detection on live ports with nmap
        nmap_result = subprocess.run(
            ["nmap", "-sV", "-sC", "-p", ",".join(live_ports), target, "-oX", "-"],
            capture_output=True, text=True, timeout=900
        )
        return self._parse_nmap_services(nmap_result.stdout)
```

**Integration**: Run port scan during the recon phase, after subdomain discovery. Map discovered services to relevant vulnerability templates:
- HTTP/HTTPS → nuclei, nikto
- SSH → nuclei-ssh templates
- MySQL/PostgreSQL/Redis → nuclei database templates

**Gated behind**: `ARGUS_FF_PORT_SCANNER=false`

**Merge criteria**: Unit tests with mocked naabu/nmap output. Integration test confirms ports are discovered and mapped to templates.

### ✅ 5.2 P4-N2: WebSocket Security Scanner — DONE

**File**: `tools/websocket_scanner.py`

**Problem**: WebSocket endpoints are a blind spot. The platform tests REST APIs but not WebSocket connections for security issues.

**Fix**: Create `tools/websocket_scanner.py` using Python's `websockets` library (already in requirements as indirect dep):

```python
class WebSocketScanner:
    """Test WebSocket endpoints for security issues."""

    async def scan(self, ws_url: str) -> list[Finding]:
        findings = []
        # Test: Origin validation
        findings.extend(await self._test_origin_validation(ws_url))
        # Test: Authentication required
        findings.extend(await self._test_auth_required(ws_url))
        # Test: Message injection
        findings.extend(await self._test_message_injection(ws_url))
        # Test: Rate limiting
        findings.extend(await self._test_rate_limiting(ws_url))
        return findings
```

**Detection**: During recon, scan page HTML for `new WebSocket()` and `wss://` patterns. Add discovered WebSocket URLs to the scan queue.

**Gated behind**: `ARGUS_FF_WS_SCANNER=false`

### ✅ 5.3 P4-N3: API Security Testing (BOLA, Auth Bypass) — DONE

**File**: `tools/api_security_scanner.py`

**Problem**: REST APIs are tested with generic web checks but specific API vulnerabilities (BOLA, mass assignment, rate limiting) are not covered.

**Fix**: Create `tools/api_security_scanner.py`:

```python
class APISecurityScanner:
    """Automated API security testing — no OpenAPI spec required."""

    async def scan(self, base_url: str, endpoints: list[str],
                   auth_headers: dict) -> list[Finding]:
        findings = []
        # BOLA: Replace user ID in path with another user's ID
        findings.extend(await self._test_bola(endpoints, auth_headers))
        # Mass assignment: Send extra fields in POST/PUT bodies
        findings.extend(await self._test_mass_assignment(endpoints, auth_headers))
        # Auth bypass: Remove/malform auth headers
        findings.extend(await self._test_auth_bypass(endpoints))
        # Rate limiting: Rapid requests to auth endpoints
        findings.extend(await self._test_api_rate_limiting(endpoints))
        return findings
```

**Discovery**: During recon, collect API endpoints from:
- JavaScript source files (fetch/XHR calls)
- Known API path patterns (`/api/`, `/v1/`, `/graphql`)
- OpenAPI/Swagger docs if discovered (`/api-docs`, `/swagger.json`, `/openapi.json`)

**Gated behind**: `ARGUS_FF_API_SCANNER=false`

### ✅ 5.4 P4-N4: Analyst Feedback Learning Loop — DONE

**File**: `models/feedback.py` + `database/migrations/016_add_finding_feedback.sql`

**Problem**: Confidence scoring and severity adjustment are static. The platform never learns from analyst corrections.

**Fix**: Create `models/feedback.py` and wire it into the existing `tool_metrics_repository.py` infrastructure:

```python
class FindingFeedback(BaseModel):
    finding_id: str
    engagement_id: str
    is_true_positive: bool
    analyst_notes: str = ""
    corrected_severity: str | None = None

class FeedbackLearningLoop:
    """Learn from analyst feedback to improve accuracy over time."""

    def on_feedback(self, feedback: FindingFeedback):
        # 1. Update finding in DB with analyst verdict
        self._update_finding(feedback)

        # 2. Update per-tool accuracy stats (uses existing tool_metrics)
        self._update_tool_accuracy(feedback)

        # 3. Adjust confidence model weights (feeds into Phase 3.1 scorer)
        self._update_confidence_model(feedback)

        # 4. Alert if a tool's FP rate exceeds threshold
        fp_rate = self._get_tool_fp_rate(feedback.finding.source_tool)
        if fp_rate > 0.30:
            self._send_alert(feedback.finding.source_tool, fp_rate)
```

**Frontend**: Add a feedback widget to the findings detail page (thumbs up/down + optional comment). Store in `finding_feedback` table.

**Gated behind**: `ARGUS_FF_FEEDBACK_LOOP=false`

---

## Phase 6: Backward Compatibility & Hardening (Weeks 12–14)

> **Goal**: Remove dead code, fix CI pipeline, add tests that prove the improvements work.
> **Risk**: Low. Mostly deletion and test additions. | **PRs**: 4-5 PRs.

### ✅ 6.1 Remove Dead Code — DONE

| ID | File | Action | Status |
|----|------|--------|--------|
| S1 | `pipeline_router.py` | Still actively used by orchestrator — left as-is | ⏳ Active |
| BEC-21 | `tools/_browser_scan_worker.py` | Removed (superseded, zero imports) | ✅ Removed |
| BEC-22 | `feature_flags.py` method `_load_flag_from_db()` | Implemented with proper DB query | ✅ Done |
| S2 | `orchestrator.py` (top-level, 501 lines) | Thin re-export, still imported by 6+ files — left as-is | ⏳ Active |

### ✅ 6.2 Fix CI Pipeline — DONE

**File**: `.github/workflows/ci.yml`

**Problem**: All lint/test steps use `continue-on-error: true` or `|| true`. CI passes even when tests fail.

**Fix**: Remove `continue-on-error` and `|| true` from all steps:
- Ruff lint: `ruff check .` (no `|| true`)
- Gitleaks: remove `continue-on-error`
- Trivy: remove `continue-on-error`

**Merge criteria**: A failing lint or test causes CI to fail.

### ✅ 6.3 Add Integration Tests for Critical Paths — DONE

**Files**: `tests/test_finding_dedup.py`, `tests/test_parallel_executor.py`, `tests/test_error_logging.py` (13 tests total)

**Add tests for**:
1. Finding deduplication (the upsert path from Phase 3.5)
2. Paginated vs unbounded finding queries (memory usage comparison)
3. Parallel executor fallback (feature flag off → sequential behavior unchanged)
4. Error handling — silent exception swallowing is now logged (verify with mock assertions)

### ✅ 6.4 BEC-12: Deduplicate JWT Logic (MEDIUM) — DONE

**Files**: `tools/web_scanner_checks/_helpers.py`, `tools/web_scanner.py`, `tools/web_scanner_checks/api_check.py`

**Problem**: JWT `alg:none` attack testing logic was copy-pasted in two places.

**Fix**: Extracted into `tools/web_scanner_checks/_helpers.py` and imported from both.

### ✅ 6.5 BEC-13: Consolidate Event Publishing (MEDIUM) — DONE

**Files**: `events/event_bus.py`, `events/__init__.py`

**Problem**: Three overlapping event systems.

**Fix**: Created `events/event_bus.py` as a unified facade. Routes all event publishing through it while keeping the underlying implementations intact.

### ✅ 6.6 BEC-01: Fix Cyrillic Character in Migration (HIGH) — DONE

**File**: `database/migrations/005_add_pgvector.sql` (line 79)

**Problem**: `embedding вектор(1536)` instead of `embedding vector(1536)`.

**Fix**: Replaced Cyrillic characters with Latin. Verified no non-ASCII chars remain.

---

## Cross-Cutting Concerns

### Feature Flags

All behavioral changes use the existing `ARGUS_FF_*` convention (already implemented in `feature_flags.py`):

| Flag | Default | Where Used |
|------|---------|------------|
| `ARGUS_FF_PARALLEL_EXECUTION` | `false` | Phase 2.1 |
| `ARGUS_FF_ML_CONFIDENCE` | `false` | Phase 3.1 |
| `ARGUS_FF_FINDING_VERIFICATION` | `false` | Phase 3.2 |
| `ARGUS_FF_PORT_SCANNER` | `false` | Phase 5.1 |
| `ARGUS_FF_WS_SCANNER` | `false` | Phase 5.2 |
| `ARGUS_FF_API_SCANNER` | `false` | Phase 5.3 |
| `ARGUS_FF_FEEDBACK_LOOP` | `false` | Phase 5.4 |

### Migration Numbering

Existing migrations: workers (004–014), platform (026–034). New migrations start at:
- Workers: `015_`
- Platform: `035_`

### Testing Requirements

| Change Type | Required |
|-------------|----------|
| Bug fix | Test that reproduces the bug + existing suite passes |
| Security fix | Test that verifies the vulnerability is closed |
| Refactor (no behavior change) | All existing tests pass |
| Performance change | Before/after timing: in CI or documented |
| Frontend decomposition | Visual comparison (screenshot or manual review) + existing tests |

---

## What We're NOT Doing

These items from v1/v2 are explicitly cut:

| Item | Reason |
|------|--------|
| Containerized tool execution (P3-S4) | No docker-compose; separate initiative |
| Redis HA / Sentinel (P3-S6) | Over-engineering for current scale |
| Full pipeline E2E test against DVWA | Requires Docker test target; document as future work |
| 9-way page decomposition (v2 FE-25 full list) | Do dashboard + findings only; others can be incremental |
| Complete TypeScript strict mode with `noUncheckedIndexedAccess` | After `any` types are eliminated, re-evaluate |
| Secret detection pre-commit hook | Useful but not structural; document for DX team |
| Docker compose for dev | No Docker in scope |

---

## Dependency Graph

```
Phase 0 (Security fixes — independent, merge immediately)
  ├── SEC-01: Remove exfiltration fetch
  ├── SEC-02: Hardcoded DB password
  ├── SEC-03: Fix IDOR
  ├── SEC-04: SSRF blocking
  ├── SEC-05: Error message exposure
  └── SEC-06: Signup rate limiting
         │
         ▼
Phase 1 (Structural — sequential, shared files)
  ├── 1.1 Connection pool consolidation ──── blocks ──► 1.4 (uses database.connection)
  ├── 1.2 Finding repo pagination
  ├── 1.3 redis.keys → SCAN
  ├── 1.5 Silent exceptions
  └── 1.6 Repository query limits
         │
         ▼
Phase 2 (Performance — feature-flagged)
  ├── 2.1 Parallel execution (depends on 1.1 for stable DB)
  ├── 2.2 Async enrichment (independent)
  ├── 2.3 Config tuning (independent)
  └── 2.4 Cache/index holdovers (independent)
         │
         ├──────────────────────────────┐
         ▼                              ▼
    Phase 3 (Accuracy)            Phase 4 (Frontend)
    ├── 3.1 Confidence scoring     ├── 4.1 Dashboard decomposition
    ├── 3.2 Finding verification   ├── 4.2 Type safety
    ├── 3.3 Payload generation     ├── 4.3 React.memo + lazy
    ├── 3.4 Parser validation      ├── 4.4 React anti-patterns
    ├── 3.5 Dedup race fix         ├── 4.5 Auth hook
    └── 3.6 Severity adjustment    ├── 4.6 Accessibility
                                   └── 4.7 Code dedup
          │                             │
          ├─────────────────────────────┘
          ▼
Phase 5 (New Capabilities)
  ├── 5.1 Port scanner (depends on 2.1 parallel exec)
  ├── 5.2 WebSocket scanner (independent)
  ├── 5.3 API security scanner (independent)
  └── 5.4 Feedback loop (depends on 3.1 confidence scoring, 3.2 verification)
          │
          ▼
Phase 6 (Hardening)
  ├── 6.1 Dead code removal
  ├── 6.2 CI pipeline fix
  ├── 6.3 Integration tests
  ├── 6.4 JWT dedup
  ├── 6.5 Event bus consolidation
  └── 6.6 Cyrillic migration fix
```

---

## Effort Summary

| Phase | Duration | PRs | Team | Risk |
|-------|----------|-----|------|------|
| 0: Security | 5 days | 6 | 1 person | Low |
| 1: Structural | 3 weeks | 6-8 | 1-2 persons | Medium |
| 2: Performance | 3 weeks | 5-7 | 1 person | Medium-High |
| 3: Accuracy | 3 weeks | 6-8 | 1 person | Medium |
| 4: Frontend | 3 weeks | 6-8 | 1 person | Medium |
| 5: New Capabilities | 3 weeks | 4-6 | 1 person | Medium |
| 6: Hardening | 2 weeks | 4-5 | 1 person | Low |
| **Total** | **~17 weeks** | **37-48** | **1-2 persons** | |

**Sequencing note**: Phase 3 (Accuracy) and Phase 4 (Frontend) run in parallel because they touch different codebases — `argus-workers/` vs `argus-platform/`. One backend engineer + one frontend engineer can work concurrently during weeks 6-9. Phase 5 (New Capabilities) starts after both complete, since some capabilities depend on accuracy infrastructure (feedback loop) and parallel execution (port scanner).

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Debug fetch removal breaks hidden integration | Low | High | `git blame` the line first; monitor production error logs for 1 week |
| Connection pool migration drops connections | Medium | Critical | Run both pools in parallel during transition; verify `_pool_lock` fix |
| Pagination breaks frontend pagination expectations | Medium | Medium | Default `limit=100` with `offset=0` — backward compatible |
| Parallel execution causes target DoS | Medium | High | Conservative `ARGUS_MAX_PARALLEL_TOOLS=3` default; rate limiter in place |
| Confidence scoring changes confuse users | Medium | Medium | Feature flag; document meaning of new scores |
| Frontend decomposition looks different | Medium | Low | Visual comparison screenshots in PR; incremental extraction |
| CI-hardening breaks developer workflow | Medium | Medium | Fix lint errors first in a prep PR, then enable strict CI |
| Port scanner naabu/nmap not installed on worker hosts | Medium | High | Check tool availability at startup; graceful fallback with clear error |
| WebSocket scanner connects to origins it shouldn't | Low | High | Scope validation: only scan WS URLs within the target's domain/scope |
| API scanner BOLA tests damage user data | Low | Critical | Read-only test mode by default (detect IDOR by response diff, not mutation) |
| Feedback loop data never gets used to retrain | High | Low | If the feedback DB table grows with no consumer, it's just unused data — not harmful |
