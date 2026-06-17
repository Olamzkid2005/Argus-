# Argus Codebase — Comprehensive Bug & Logic Sweep Report

**Date:** 2026-06-17  
**Scope:** Full codebase audit (~200 files)  
**Total findings:** ~150  
**Severity breakdown:** 15 CRITICAL, 20+ HIGH, ~40 MEDIUM, ~75 LOW/INFO

---

## Priority Fix Order

1. CRITICAL items first (data loss, security bypass, crashes)
2. HIGH items next (incorrect results, resource leaks, limited exploits)
3. MEDIUM items as time permits
4. LOW/INFO items for hardening

---

# CRITICAL

---

## C-01: LLM Agent Scope Validation Is Dead Code — Never Called

**Files:** `agent/react_agent.py:570-628` (definition), `:842` (call site)  
**Type:** Broken Access Control / SSRF

### Bug
`ReActAgent._validate_arguments()` implements critical scope validation — blocking internal/private IPs, cloud metadata endpoints (AWS/GCP/Azure), loopback addresses. It checks all common target parameter names (`target`, `url`, `host`, `hostname`, `domain`, `endpoint`). **However, this method is NEVER invoked from the execution path.**

The agent loop at line 842 calls `self.registry.call(action.tool, **action.arguments)` directly. `ToolRegistry.call()` only validates parameter schemas (required, type, enum) — it does **not** validate target scope. `_validate_arguments()` is completely unreachable dead code.

### Impact
Complete SSRF bypass. An attacker controlling the LLM output (via prompt injection from a compromised target) can direct the agent to attack `169.254.169.254` (AWS/GCP metadata), `localhost`, or any internal host.

### Fix
Insert the call to `_validate_arguments()` in `run()` before executing the tool at line 842:

```python
# Before line 842 in react_agent.py run()
if not self._validate_arguments(action):
    logger.warning("Blocked tool %s due to scope validation failure", action.tool)
    result = AgentResult(tool=action.tool, success=False,
                         error=f"Blocked by scope validation: {action.tool}")
    results.append(result)
    continue  # skip execution, move to next iteration
```

---

## C-02: `cache_mode` Passed to Functions Without the Parameter

**Files:** `pipeline_router.py:36,68`  
**Type:** Runtime Crash

### Bug
`execute_recon_pipeline()` (line 36) passes `cache_mode=cache_mode` to `execute_recon_tools()` in `recon.py`, which has no such parameter. Similarly, `execute_scan_pipeline()` (line 68) passes `cache_mode=cache_mode` to `execute_scan_tools()` in `scan.py`, which also lacks it. Both calls will fail with `TypeError: unexpected keyword argument 'cache_mode'` at runtime.

### Impact
Any scan or recon pipeline dispatch will crash, preventing the entire engagement from proceeding. The worker task will fail with an unhandled exception, leaving the engagement stuck.

### Fix
Add the `cache_mode` parameter to both functions:

```python
# In recon.py execute_recon_tools():
def execute_recon_tools(ctx, target, budget, aggressiveness=DEFAULT_AGGRESSIVENESS, cache_mode=None):

# In scan.py execute_scan_tools():
def execute_scan_tools(ctx, targets, budget, aggressiveness=DEFAULT_AGGRESSIVENESS,
                       auth_config=None, dual_auth_config=None, tech_stack=None,
                       skip_tools=None, recon_context=None, cache_mode=None):
```

---

## C-03: AgentSessionStore — Unbounded Memory Growth + No Thread Safety

**Files:** `agent/session_store.py:54-55,83-97,99-110`  
**Type:** Resource Exhaustion / Race Condition

### Bug
`AgentSessionStore._sessions` is a plain `dict[str, AgentSession]` with:
1. **No eviction policy** — sessions accumulate forever, eventually OOM-killing the process.
2. **No thread safety** — all methods read/write `self._sessions` without any lock. Under concurrent access this causes dict corruption, lost writes, and `KeyError`.

### Impact
Persistent memory leak until OOM. Data corruption in multi-threaded scenarios (swarm agents).

### Fix
Add threading locks and TTL-based eviction:

```python
import threading

class AgentSessionStore:
    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()
        self._start_eviction_loop()

    def create(self, ...) -> str:
        with self._lock:
            self._sessions[session_id] = session
            return session_id

    def get(self, session_id: str) -> AgentSession:
        with self._lock:
            if session_id not in self._sessions:
                raise ValueError(...)
            return self._sessions[session_id]

    def _eviction_loop(self):
        while True:
            time.sleep(300)  # every 5 mins
            now = time.time()
            with self._lock:
                expired = [sid for sid, s in self._sessions.items()
                           if now - s.created_at > 3600]  # 1 hour TTL
                for sid in expired:
                    del self._sessions[sid]
```

---

## C-04: Auth Credentials Stored in Plaintext in Database

**Files:** `agent/auth_checkpoint.py:46-62`, `agent/auth_context.py:69-83`  
**Type:** Sensitive Data Exposure

### Bug
`AuthContext.to_dict()` serializes `email` and `password` as plain strings. This dict is stored via `save_auth_checkpoint()` into the `agent_decision_log.arguments` column as raw JSON. Credentials persist indefinitely in plaintext.

Additionally, the INSERT uses `ON CONFLICT (id) DO NOTHING` but `id` is auto-generated — every checkpoint call creates a **new row** rather than updating, causing unbounded table growth.

### Impact
Any user/process with DB read access can extract plaintext credentials. DB backups contain secrets.

### Fix
Encrypt the password before storage and fix the UPSERT:

```python
from cryptography.fernet import Fernet

# On save:
cipher = Fernet(os.environ["AUTH_CHECKPOINT_KEY"].encode())
data["password"] = cipher.encrypt(data["password"].encode()).decode()

# On load:
data["password"] = cipher.decrypt(data["password"].encode()).decode()
```

Fix the INSERT to use proper UPSERT:
```sql
INSERT INTO agent_decision_log (...) VALUES (...)
ON CONFLICT (engagement_id, action_id)
DO UPDATE SET arguments = EXCLUDED.arguments, created_at = NOW()
```

Requires a unique constraint:
```sql
CREATE UNIQUE INDEX idx_auth_checkpoint_unique
ON agent_decision_log (engagement_id, action_id)
WHERE action_id = 'auth_context';
```

---

## C-05: Operator Cancel Returns Before `yield` in `@contextmanager` — RuntimeError

**Files:** `tasks/base.py:197`  
**Type:** Runtime Crash

### Bug
The operator cancellation check (lines 190-199) executes `return` at line 197 when a cancel signal is found. This happens **before** `yield ctx` at line 201. In Python 3.7+, a `@contextmanager`-decorated generator that returns before yielding raises `RuntimeError: generator didn't yield`.

### Impact
Operator cancellation is completely broken — it triggers a RuntimeError rather than a graceful abort. The `LockContext` at line 166 may not release cleanly.

### Fix
Replace the `return` with a sentinel exception:

```python
class OperatorCanceled(Exception):
    pass

# At line 197:
state.transition("failed", "Cancelled by operator")
raise OperatorCanceled("Engagement cancelled by operator")

# Add to except chain at line 216:
except OperatorCanceled:
    raise  # propagate cleanly
except Exception as e:
    ...
```

---

## C-06: `requests.Session` Shared Across ThreadPoolExecutor Workers

**Files:** `tools/web_scanner.py:289,480,539,565`  
**Type:** Race Condition / Data Corruption

### Bug
`WebScanner._run_scan_impl()` submits 38+ check methods to a `ThreadPoolExecutor(max_workers=6)`. Every check calls `_safe_request()` which uses `self.session` — a single `requests.Session` instance shared across all threads. The `requests` library explicitly prohibits this. Concurrent requests cause cookie jar corruption, connection pool corruption, SSL context races, and header mutation.

### Impact
Silently corrupts scan results (wrong auth context), causes hard-to-diagnose HTTP errors, and can lead to incorrect vulnerability findings or crashes.

### Fix
Use thread-local sessions:

```python
# In __init__:
self._thread_session = threading.local()

# In _safe_request:
req_session = getattr(self._thread_session, 'session', None)
if req_session is None:
    req_session = requests.Session()
    req_session.headers.update(self.session.headers)
    self._thread_session.session = req_session
```

---

## C-07: Non-Serialization Exceptions Silently Swallowed in Snapshot Retry Loop

**Files:** `snapshot_manager.py:165-181`  
**Type:** Silent Failure / Data Loss

### Bug
The `create_snapshot` retry loop (max_retries=3) only retries on `SERIALIZATION_FAILURE` (pgcode 40001). For any other exception, the code silently falls through to the next iteration without raising or logging. Only the *last* attempt propagates the error.

### Impact
DB connection errors are masked during snapshot creation. The snapshot may silently fail after exhausting retries for unrelated reasons.

### Fix
Re-raise all non-serialization exceptions immediately:

```python
except Exception as e:
    if conn:
        conn.rollback()
    if hasattr(e, 'pgcode'):
        from psycopg2.errorcodes import SERIALIZATION_FAILURE
        if e.pgcode == SERIALIZATION_FAILURE and attempt < max_retries - 1:
            logger.info(...)
            time.sleep(...)
            continue
    raise  # Re-raise all other exceptions immediately
```

---

## C-08: `_with_reconnect` Retry Uses Stale Bound Method — Never Reconnects

**Files:** `distributed_lock.py:63-79`  
**Type:** Logical Error / Connection Recovery Broken

### Bug
When `_with_reconnect` is called, the `operation` argument is a *bound method* of the old Redis client. If the first attempt fails, `self._redis_client` is set to `None` but the retry calls `operation(*args, **kwargs)` which is still bound to the **old, broken client**.

### Impact
Heartbeat and lock operations silently fail after Redis disconnections. Workers may lose distributed locks and cause duplicate engagement processing.

### Fix
Pass the method name and re-bind on retry:

```python
def _with_reconnect(self, method_name: str, *args, **kwargs):
    try:
        operation = getattr(self.redis_client, method_name)
        return operation(*args, **kwargs)
    except (redis.ConnectionError, redis.TimeoutError, OSError) as e:
        logger.warning("...")
        self._redis_client = None
        operation = getattr(self.redis_client, method_name)  # new binding
        return operation(*args, **kwargs)
```

---

## C-09: Health Monitor Consecutive Failure Count Wrong (DESC Order)

**Files:** `health_monitor.py:310-328`  
**Type:** Logic Error / Incorrect Results

### Bug
The query uses `ORDER BY tool_name, created_at DESC` which returns rows newest-first per tool. The consecutive_failures counter increments on failure and resets on success. Because iteration is newest-first, hitting a success at the *latest* record resets the counter to 0, then older failures increment it again. The final count reflects *older* failures rather than immediately-consecutive failures.

### Impact
Tool health status (`down`/`degraded`/`healthy`) is computed incorrectly. Self-healing logic may fail to trigger.

### Fix
Stop iterating when the most recent success is hit:

```python
for row in all_metrics:
    tool = row[0]
    success = row[1]
    if tool not in cons_failures:
        cons_failures[tool] = 0
    if not success:
        cons_failures[tool] += 1
    else:
        break  # Stop: we hit the most recent success
```

---

## C-10: Race on Global Redis Client Singleton

**Files:** `cache.py:29-58`  
**Type:** Race Condition

### Bug
Module-level `_redis_client_instance` and `_redis_available` are accessed and mutated by `_get_redis()` without any lock. Two concurrent threads can race: one creates a new client while another gets a stale reference. Connections are leaked when the second thread overwrites `_redis_client_instance` without closing the first.

### Fix
Add a threading lock:

```python
_redis_lock = threading.Lock()

def _get_redis():
    global _redis_client_instance, _redis_available
    with _redis_lock:
        if _redis_client_instance is not None:
            try:
                _redis_client_instance.ping()
                return _redis_client_instance
            except Exception:
                with contextlib.suppress(Exception):
                    _redis_client_instance.close()
                _redis_client_instance = None
                _redis_available = False
        try:
            import redis as redis_lib
            _redis_client_instance = redis_lib.from_url(...)
            _redis_client_instance.ping()
            _redis_available = True
            return _redis_client_instance
        except Exception as e:
            ...
```

---

## C-11: Execution Engine — Scope Validation Bypasses Positional Args

**Files:** `runtime/execution_engine.py:61-74`  
**Type:** Security Boundary Bypass

### Bug
The scope validation middleware only inspects `kwargs` for target-bearing parameters (`target`, `url`, `host`, etc.). But tool targets can be passed as positional `args`. The scope validator **never inspects `args`**.

### Impact
Any tool invocation with the target in positional arguments bypasses scope validation entirely.

### Fix
Add args inspection to the scope middleware:

```python
def _scope_check(tool_name, args, kwargs):
    for param in target_params:
        tgt = kwargs.get(param, "")
        ...
    for arg in (args or []):
        if isinstance(arg, str) and scope_validator.looks_like_target(arg):
            try:
                scope_validator.validate_target(arg)
            except Exception:
                return None
```

---

## C-12: Execution Engine — Keyword Arguments Silently Dropped

**Files:** `runtime/execution_engine.py:124`  
**Type:** Silent Correctness Bug

### Bug
The `execute()` method accepts `**kwargs` (line 90) but never forwards them to `tool_runner.run()`. Yet kwargs ARE included in the execution record for logging — creating a deceptive audit trail.

### Impact
Any caller passing `target=`, `rate_limit=`, `custom_flags=` has them silently ignored. Incorrect tool behavior with no warning.

### Fix
Forward kwargs to tool_runner.run():

```python
result = self.tool_runner.run(tool_name, args, timeout=timeout, **kwargs)
```

---

## C-13: Event Stream — Persist/Commit/Emit Ordering Violation

**Files:** `runtime/event_stream.py:232-236`  
**Type:** Data/Event Desync

### Bug
The `transactional_event_context` context manager uses `except Exception: discard(); raise` / `else: flush()`. If code inside the `with` block commits to DB *before* an unrelated exception is raised, queued events are silently discarded while DB data persists — creating phantom data with no event trail.

### Impact
UI silently misses findings/state changes even though they are persisted.

### Fix
Restructure to separate the commit boundary. Either move the DB commit outside the context manager, or add a `mark_committed()` call:

```python
class TransactionalEmitter:
    def mark_committed(self):
        self._committed = True

    def __exit__(self, exc_type, ...):
        if exc_type and not self._committed:
            self._queue.clear()  # discard only if not committed
            return
        self.flush()
```

---

## C-14: Code Generation — Unescaped String Defaults Break Generated Python

**Files:** `scripts/generate_tool_defs.py:78-81`  
**Type:** Worker Startup Crash

### Bug
When a YAML `default` value contains a double quote (`"`), the generated code is syntactically invalid Python, preventing the entire module from loading. Numeric defaults are also wrapped in quotes, changing `default=42` to `default="42"`.

### Impact
Worker crash on startup if any tool definition YAML contains double-quoted defaults. Type errors for numeric parameters.

### Fix
Use JSON serialization for safe escaping:

```python
import json
escaped_default = json.dumps(default)  # handles str, int, float, bool, None
args += f", default={escaped_default}"
```

---

## C-15: Stored XSS in HTML Report Remediation Text

**Files:** `reporting/html_report.py:293-298`  
**Type:** Stored Cross-Site Scripting

### Bug
Remediation text is placed inside a JavaScript `onclick` handler via string concatenation. `html.escape()` does NOT escape JavaScript metacharacters. HTML parser resolves `&quot;` back to `"` for the JS interpreter, enabling XSS.

Example PoC remediation: `"); alert(document.cookie); //`

### Impact
Any finding with a crafted remediation string executes arbitrary JavaScript in the report viewer's browser.

### Fix
Use `json.dumps()` for JavaScript-safe string embedding:

```python
import json
btn_click = f"copyFix({json.dumps(remediation)}, this)"
```

---

# HIGH

---

## H-01: Prompt Injection via Tool Output in Parser Fallback

**Files:** `llm_parser_fallback.py:166-174`  
**Type:** Prompt Injection

### Bug
`LLMParserFallback.extract_findings()` sends raw tool output (originating from the scanned target) directly into the LLM prompt. Sanitization is weak — regex patterns are easily bypassed via Unicode homoglyphs, zero-width joiners, or simple rephrasing.

### Fix
Wrap tool output in base64 encoding to completely prevent injection:

```python
import base64
encoded_output = base64.b64encode(sanitized_output.encode()).decode()
user_prompt = (
    f"Tool: {tool_name}\n\n"
    f"Raw output (base64): {encoded_output}\n\n"
    "Decode the base64 output and extract findings."
)
```

---

## H-02: Circuit Breaker Threshold Set to 1

**Files:** `llm_client.py:126`  
**Type:** Availability Degradation

### Bug
`self._circuit_threshold = 1` means a single failure opens the circuit for 60 seconds. Even transient errors (network hiccup, DNS timeout) block ALL subsequent LLM calls.

### Fix
```python
self._circuit_threshold = 5   # Require 5 consecutive failures
self._circuit_cooldown = 30.0 # Shorter cooldown
```

---

## H-03: `memory_context` Unsanitized — Direct Prompt Injection Vector

**Files:** `agent/agent_prompts.py:762-763`  
**Type:** Prompt Injection

### Bug
The `memory_context` parameter is inserted into the LLM prompt WITHOUT sanitization. An attacker who influenced previous scan data could inject prompt-altering content across sessions.

### Fix
```python
if memory_context:
    sanitized_memory = _sanitize_for_llm(str(memory_context))
    prompt_parts.append(f"=== MEMORY CONTEXT ===\n{sanitized_memory}")
```

---

## H-04: WebSocket Publisher Redis Connection Not Thread-Safe

**Files:** `websocket_events.py:77-86`  
**Type:** Connection Leak

### Bug
The `redis` property lazy-initializes the connection without any lock. Two concurrent threads create two connections — the first is leaked. No reconnection logic exists if Redis drops mid-operation.

### Fix
```python
@property
def redis(self) -> redis.Redis:
    if self._redis is None:
        self._redis = redis.from_url(...)
    try:
        self._redis.ping()
    except Exception:
        self._redis = redis.from_url(...)
    return self._redis
```

Add a threading lock around initialization.

---

## H-05: `_rt_emitted_fingerprints` Unbounded Memory Growth

**Files:** `streaming.py:692-693,706-713`  
**Type:** Memory Leak

### Bug
The in-flight dedup store `_rt_emitted_fingerprints` grows monotonically with each unique finding. `clear_engagement_rt_fingerprints()` exists but has **no callers** (sic — this function is never invoked anywhere).

### Fix
Use an LRU cache (`cachetools.TTLCache`) or schedule periodic cleanup:

```python
from cachetools import TTLCache
_rt_emitted_fingerprints: dict[str, set[str]] = defaultdict(
    lambda: set()  # or TTLCache for TTL-based eviction
)
```

Integrate cleanup into engagement lifecycle hooks.

---

## H-06: Fingerprint Dedup TOCTOU Race

**Files:** `orchestrator_pkg/scan.py:288-290,323-329`  
**Type:** Duplicate Findings

### Bug
```python
fps = _get_fingerprint_set(ctx.engagement_id)
if fp in fps:        # check (outside lock)
    continue
fps.add(fp)          # add (outside same lock)
```

Between the `in` check and `add`, another thread could add the same fingerprint.

### Fix
```python
def _dedup_fingerprint(engagement_id: str, fp: str) -> bool:
    with _emitted_fingerprints_lock:
        fps = _emitted_fingerprints.get(engagement_id)
        if fps is None:
            fps = set()
            _emitted_fingerprints[engagement_id] = fps
        if fp in fps:
            return False
        fps.add(fp)
        return True
```

---

## H-07: Silent Data Loss When ALL Saves Fail

**Files:** `orchestrator_pkg/orchestrator.py:240-243,463-466`  
**Type:** Data Loss

### Bug
Both `run_recon()` and `run_scan()` call `_save_findings()` and check the number of failures. But they **never stop the pipeline** regardless of how many findings fail to save. If all findings fail, the engagement transitions to `"completed"` with 0 findings.

### Fix
```python
failed_saves = self._save_findings(findings)
if failed_saves > 0:
    slog.warning(f"{failed_saves}/{findings_count} scan findings failed to save")
    if failed_saves == findings_count:
        raise RuntimeError(f"All {findings_count} findings failed to save — aborting phase")
```

---

## H-08: Tokens/Findings Missing After Parallel Phase Execution (Variable Shadowing)

**Files:** `orchestrator_pkg/orchestrator.py:366-368,480-482`  
**Type:** Silent Data Loss

### Bug
In `run_scan()`, the outer `all_findings` list accumulates findings from the agent path. The fallback path at line 480 uses `all_findings = self._run_scan_with_fallback(...)`. This **reassigns** the outer variable instead of **extending** it, discarding any findings collected before the fallback.

### Fix
```python
# Line 480 — change from:
all_findings = self._run_scan_with_fallback(...)
# To:
all_findings.extend(self._run_scan_with_fallback(...))
```

---

## H-09: DLQ `error_message` Not Redacted for Secrets

**Files:** `dead_letter_queue.py:108-141`  
**Type:** Credential Leak

### Bug
The `enqueue` method redacts `kwargs` and `args` but stores `error_message` raw. Exception messages commonly include credentials (e.g., `"Connection to postgresql://user:pass@host/db failed"`).

### Fix
```python
safe_error = error_message
for pattern in self._SECRET_VALUE_PATTERNS:
    safe_error = pattern.sub("__REDACTED__", safe_error)
```

---

## H-10: SIGALRM Leaks TCP Connections in Register Tool

**Files:** `agent/tools/register_tool.py:111-131,307-327`  
**Type:** Resource Leak

### Bug
`SIGALRM` is used as a hard deadline. When the alarm fires during an HTTP call, the signal handler raises `TimeoutError` but the underlying TCP socket is not closed. On Windows, the `threading.Timer` only sets a flag — the HTTP call continues running in the background.

### Fix
Replace SIGALRM with connection-level timeouts:

```python
http_session = requests.Session()
http_session.mount('https://', requests.adapters.HTTPAdapter(
    max_retries=0, pool_connections=1, pool_maxsize=1,
))
resp = http_session.post(url, data=body, timeout=(5, 30))  # connect=5s, read=30s
```

Remove SIGALRM entirely.

---

## H-11: Unvalidated Vulnerability Type Strings Accepted

**Files:** `tool_core/finding_builder.py:53-88`, `models/finding.py:66-72`  
**Type:** Data Integrity

### Bug
`FindingBuilder.add()` validates severity against `SEVERITIES` frozenset, but `finding_type` is never validated against any known list. Arbitrary type strings pass into the DB and downstream into LLM prompts, confidence scoring, and reports.

### Fix
Introduce a `KnownVulnType(StrEnum)` and validate against it:

```python
class KnownVulnType(StrEnum):
    SQL_INJECTION = "SQL_INJECTION"
    XSS = "XSS"
    ...

def add(self, finding_type, ...):
    if finding_type not in KnownVulnType.__members__.values():
        raise ValueError(f"Unknown finding type: {finding_type}")
```

---

## H-12: `REDIS_URL` Logged with Credentials Before Redaction Filter Installed

**Files:** `config/redis.py:13-19`  
**Type:** Credential Leak

### Bug
Module-level code executes `logger.warning("REDIS_URL not set — defaulting to %s. ...", REDIS_URL)` at **import time**. If `REDIS_URL` contains credentials (e.g., `redis://:password@host:6379`), they are written to the log before the secrets redaction filter is installed.

### Fix
Remove the REDIS_URL warning from module-level. Move to a lazy initialization function.

---

## H-13: CWE List Causes `AttributeError` Crash in Normalizer

**Files:** `parsers/normalizer.py:373-378` / `parsers/parsers/semgrep.py:60-61`  
**Type:** Crash / Data Loss

### Bug
The `_normalize_type()` method reads `evidence.get("cwe", "")` and calls `.upper()` on it. Semgrep's `cwe` field can be a **list of strings** (`["CWE-78", "CWE-94"]`). `list.upper()` raises `AttributeError`, crashing the normalizer and losing the finding.

### Fix
```python
cwe_raw = evidence.get("cwe", "")
if isinstance(cwe_raw, list):
    cwe_raw = cwe_raw[0] if cwe_raw else ""
cwe = str(cwe_raw).upper()
```

---

## H-14: Parameter Discovery and Parameter Fuzzing Race on Shared State

**Files:** `tools/web_scanner.py:1194-1272,1291-1363`  
**Type:** Silent Skip

### Bug
Both `parameter_discovery()` and `parameter_fuzzing()` are submitted simultaneously to the ThreadPoolExecutor. They share `self.discovered_parameters` with no synchronization. If `parameter_fuzzing` executes before `parameter_discovery` initializes the field, it immediately returns with zero tests performed — no error, no log.

### Fix
Run parameter_discovery first, sequentially, then submit the remaining checks to the pool:

```python
self.parameter_discovery()
# Then submit remaining checks (excluding discovery and fuzzing)
checks = [c for c in checks if c not in (self.parameter_discovery, self.parameter_fuzzing)]
# ...ThreadPoolExecutor...
self.parameter_fuzzing()
```

---

## H-15: Connection Leak on `conn.cursor()` Failure

**Files:** `database/repositories/base.py:248-249`  
**Type:** Connection Pool Exhaustion

### Bug
```python
conn = self._get_connection()
cursor = conn.cursor(...)  # can raise
try:
    yield ...
finally:
    cursor.close()
    conn.close()
```
If `conn.cursor()` raises, `conn` is assigned but the try/finally block is never entered. The connection is never released back to the pool.

### Fix
```python
conn = self._get_connection()
try:
    cursor = conn.cursor(cursor_factory=cursor_factory)
except Exception:
    self._release_connection(conn)
    raise
```

---

## H-16: Evidence Sanitization Silently Fails — Unsanitized Data Stored

**Files:** `tool_core/finding_builder.py:156-163`  
**Type:** XSS / Data Integrity

### Bug
`_sanitize()` has a bare `except ImportError: return evidence`. If the sanitization module is missing or import paths change, all evidence containing HTML/JS injection payloads passes through unsanitized. This data is stored in PostgreSQL and served to the UI.

### Fix
Remove the silent fallback. Make sanitization mandatory:

```python
try:
    from utils.sanitization import sanitize_evidence
except ImportError:
    raise RuntimeError("Sanitization module required but not available")
```

---

## H-17: `reset_tenant_context()` Causes Complete Data Invisibility

**Files:** `database/connection.py:266-271`, `database/migrations/008_add_tenant_isolation.sql:73-78`  
**Type:** Silent Empty Results

### Bug
`reset_tenant_context()` sets `app.current_org_id` to an empty string `''`. When `get_current_org_id()` is called, `''::UUID` raises. The RLS policy `org_id = NULL` is always `false`, making all subsequent queries return zero rows silently.

### Fix
Use a sentinel UUID:

```python
set_config('app.current_org_id', '00000000-0000-0000-0000-000000000000', false)
```

Update the RLS policy function to check for this sentinel.

---

## H-18: Event Listener Leak in Playwright Browser Scan

**Files:** `tools/_browser_scan_worker.py:76-85`  
**Type:** Memory Leak / False Positives

### Bug
Each payload iteration registers a **new** `page.on('console', ...)` listener that is **never removed**. After N iterations, there are N active listeners, all firing on every console event. Old listeners write to stale lists, and alerts from the current navigation get attributed to multiple payload iterations.

### Fix
Remove listeners before registering new ones:

```python
current_errors = []
def on_console(msg):
    if msg.type == 'error':
        current_errors.append(msg.text)

page.on('console', on_console)

for payload in PAYLOADS:
    current_errors = []  # rebind, don't recreate listener
    ...
```

Or use `page.remove_listener('console', handler)` before adding a new one.

---

## H-19: Duplicate Risk Check Block in `validate_tool_alignment.py`

**Files:** `scripts/validate_tool_alignment.py`  
**Type:** Logic Bug (Already Fixed)

### Bug (Already Fixed per ARCHITECTURE_AUDIT.md)
The `validate()` function contained a duplicate risk mismatch check — the `_is_destructive()` validation block appeared twice in succession (lines 97-108 and 110-121). Any tool with a risk mismatch produced **two identical error messages**.

### Fix
Remove the duplicate block.

---

## H-20: Swarm Agents Lack Scope Validation

**Files:** `agent/swarm.py:196-247,269-331`  
**Type:** Incomplete Authorization

### Bug
Only `APIAgent.run()` calls `validate_target_scope()`. `IDORAgent` and `AuthAgent` run all their tools with zero scope validation. Targets come from `ReconContext.live_endpoints`, `api_endpoints`, `crawled_paths`, and `target_url` — none validated against authorized scope.

### Fix
Add scope validation in `SpecialistAgent._get_targets()`:

```python
def _get_targets(self) -> list[str]:
    raw_targets = self._get_raw_targets()
    if hasattr(self, 'engagement_id'):
        from tools.scope_validator import filter_authorized_targets
        return filter_authorized_targets(raw_targets, self.engagement_id)
    return raw_targets
```

---

# MEDIUM

---

## M-01: `_persist_scanner_activity` INSERT Fails Silently with None Values

**Files:** `websocket_events.py:589-601`  
**Type:** Data Loss

### Bug
`items_found` and `duration_ms` default to `None`. If the corresponding DB column is `NOT NULL`, the INSERT fails silently (exception caught and logged at WARNING).

### Fix
Coerce None values to 0 before INSERT:
```python
items_found = items_found or 0
duration_ms = duration_ms or 0
```

---

## M-02: `UnboundLocalError` When `conn.cursor()` Fails in `get_transition_history`

**Files:** `state_machine.py:329`  
**Type:** Crash

### Bug
Unlike `_persist_state_and_budget` (which initializes `cursor = None`), `get_transition_history` does not initialize `cursor` before the `try` block. If `conn.cursor()` raises, the `finally` block references unbound `cursor`, causing `UnboundLocalError` that masks the original exception.

### Fix
```python
def get_transition_history(self) -> list[dict]:
    conn = None
    cursor = None        # ADD THIS
    try:
        conn = self._get_connection()
        cursor = conn.cursor()
```

---

## M-03: Path Traversal in Vault Secret Key

**Files:** `secrets_manager.py:100-101`  
**Type:** Privilege Escalation

### Bug
The `key` parameter is directly interpolated into the Vault path without sanitization. If `key` contains `../`, an attacker can read secrets from other Vault paths.

### Fix
```python
import re
safe_key = re.sub(r'[^a-zA-Z0-9_\-]', '', key)
response = vault.secrets.kv.v2.read_secret_version(path=f"{path}/{safe_key}")
```

---

## M-04: UPSERT Overwrites Instead of Incrementing Loop Budget

**Files:** `loop_budget_manager.py:110-144`  
**Type:** Incorrect Budget Tracking

### Bug
The UPSERT uses `EXCLUDED.current_cycles` which overwrites the existing value. Compare with `state_machine.py` which correctly uses `current_cycles + 1`.

### Fix
```sql
DO UPDATE SET
    current_cycles = loop_budgets.current_cycles + EXCLUDED.current_cycles,
    ...
```

---

## M-05: `cached` Decorator Never Caches `None` Results

**Files:** `cache.py:349-371`  
**Type:** Performance

### Bug
`cache.get()` returns `None` for both "key not found" and "cached JSON null". A function that legitimately returns `None` is always re-executed.

### Fix
Use a sentinel object:
```python
_MISS = object()
cached_value = cache.get(key)
if cached_value is not _MISS:
    return cached_value
```

---

## M-06: `"invalid"` in PERMANENT_INDICATORS Over-Classification

**Files:** `error_classifier.py:89`  
**Type:** Incorrect Classification

### Bug
The substring `"invalid"` in `PERMANENT_INDICATORS` matches ANY error message containing it (e.g., `"Invalid response from upstream server"` is classified permanent, should_retry=False).

### Fix
Remove `"invalid"` or use more specific patterns like `"invalid input"`, `"invalid request"`.

---

## M-07: Event Data Shape Inconsistency Between Transactional and Direct Paths

**Files:** `streaming.py:357-366`  
**Type:** Consumer Breakage

### Bug
The transactional path wraps `details` in a sub-key while the direct path spreads it into the top-level data. Consumers receive different structures depending on which path is active.

### Fix
Normalize both paths to use the same key structure.

---

## M-08: `emit_agent_decision` Uses Wrong Event Type

**Files:** `streaming.py:542-554`  
**Type:** Broken Consumers

### Bug
`EventType.AGENT_DECISION` is defined but `emit_agent_decision` publishes with `EventType.THINKING`. Consumers filtering on `AGENT_DECISION` never receive these events.

### Fix
```python
get_stream_manager().publish(Event(
    type=EventType.AGENT_DECISION,  # was EventType.THINKING
    ...
))
```

---

## M-09: `is_in_scope` Uses String Prefix — SSRF via Subdomain Squatting

**Files:** `tools/dual_auth_scanner.py:407`  
**Type:** SSRF

### Bug
```python
if absolute.startswith(self.target_url)
```
A URL like `https://example.com.attacker-controlled.com` passes if `self.target_url = "https://example.com"`.

### Fix
Use hostname-based matching (same pattern as `web_scanner.py:_is_in_scope()`):
```python
def _is_in_scope(url, target_url):
    parsed_url = urlparse(url)
    parsed_target = urlparse(target_url)
    return (parsed_url.hostname == parsed_target.hostname or
            parsed_url.hostname.endswith("." + parsed_target.hostname))
```

---

## M-10: `sanitize_redis_key` Causes Key Collisions

**Files:** `utils/validation.py:15-31`  
**Type:** Data Corruption

### Bug
All non-alphanumeric characters are replaced with `_`. Keys `"user:name"` and `"user_name"` both become `"user_name"`.

### Fix
Use percent-encoding or reject invalid keys:
```python
import urllib.parse
return urllib.parse.quote(key, safe='')
```

---

## M-11: All Line-Based Parsers — Windows `\r\n` Truncation

**Files:** All 31 parser files in `parsers/parsers/*.py`  
**Type:** Silent Data Loss on Windows

### Bug
Most parsers use `raw_output.split("\n")` which does NOT handle Windows `\r\n`. The trailing `\r` causes URL validation failures, prefix matching failures, etc.

### Fix
Replace `raw_output.split("\n")` with `raw_output.splitlines()` everywhere.

---

## M-12: No LLM Fallback in Streaming Mode

**Files:** `parsers/parser.py:180-259`  
**Type:** Reduced Resilience

### Bug
`parse_stream()` has no LLM fallback when the parser returns no findings or raises. In streaming mode, large tool outputs that fail parsing are entirely lost.

### Fix
Add LLM fallback to `parse_stream()`:
```python
try:
    for finding in parser.parse_stream(raw_output):
        ...
except Exception as e:
    llm_findings = self._try_llm_fallback(tool_name, raw_output)
    for batch in self._batch_findings(llm_findings, batch_size):
        yield batch
    return
```

---

## M-13: Token Tracking Uses Fictional Estimates

**Files:** `runtime/governance.py:111-115,224-239`  
**Type:** Broken Budget Enforcement

### Bug
`_estimate_token_usage()` returns hardcoded estimates per tool name (nuclei=200, semgrep=150, etc.). The field `_total_tokens_used` is accumulated with invented numbers having no relationship to actual LLM consumption.

### Fix
Track actual token usage from the LLM client response, or rename to clarify it's an estimate and adjust thresholds accordingly.

---

## M-14: Thread Locks Useless Across Celery Processes

**Files:** `runtime/shadow_mode.py:37,93-96`  
**Type:** Incorrect Counters

### Bug
`_counter_lock` is `threading.Lock()` but Celery workers are forked processes. Thread locks do NOT synchronize across processes. Shadow mode counters are unreliable in multi-worker deployments.

### Fix
Use a shared store (Redis or DB) for shadow mode counters, or document that shadow mode is per-process only.

---

## M-15: `validate_tool_alignment.py` Relative Paths Break CI

**Files:** `scripts/validate_tool_alignment.py:33-34`  
**Type:** CI Reliability

### Bug
Paths are hardcoded relatives that only work when the script is run from `argus-workers/` as CWD. Any CI running from a different directory gets `FileNotFoundError` or silently empty results.

### Fix
Resolve paths relative to the script location:
```python
_SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON_DEFS_DIR = _SCRIPT_DIR.parent / "tools" / "definitions"
TUI_DEFS_PATH = _SCRIPT_DIR.parent / "../Argus-Tui/..."
```

---

# LOW / INFO (Selected)

---

## L-01: `import re` Inside Hot-Path Cache Method

**Files:** `cache.py:110-126`  
**Fix:** Move `import re` to module level.

---

## L-02: `clear_engagement_rt_fingerprints` Has No Callers

**Files:** `streaming.py:706-713`  
**Fix:** Call from engagement cleanup/completion handlers.

---

## L-03: `stop_callback` Naming Semantics Inverted

**Files:** `distributed_lock.py:266`  
**Fix:** Rename to `is_done_callback`.

---

## L-04: `db.cursor()` Context Manager Incompatible with psycopg2 < 2.9

**Files:** `feature_flags.py:139`  
**Fix:** Explicitly manage cursor lifecycle (try/finally close).

---

## L-05: `shutdown_handler.restore()` Crashes from Non-Main Thread

**Files:** `shutdown_handler.py:93-97`  
**Fix:** Check `threading.current_thread() is threading.main_thread()`.

---

## L-06: `requests.Session` Not Closed in LoginTool

**Files:** `tools/login.py:23`  
**Fix:** Use `with requests.Session() as session:` context manager.

---

## L-07: `verify_xss` Payloads Not URL-Encoded

**Files:** `tools/finding_verifier.py:198-200`  
**Fix:** Use httpx `params` parameter for proper URL encoding.

---

## L-08: Md5 Used for Endpoint IDs in jwt_tool Parser

**Files:** `parsers/parsers/jwt_tool.py:95,107`  
**Fix:** Use `hashlib.sha256()[:8]` instead.

---

## L-09: `json.dumps(sbom_json)` Can Crash Report Upsert

**Files:** `database/repositories/report_repository.py:93`  
**Fix:** Wrap in try/except with `default=str`.

---

## L-10: No Migration Runner or Tracking Table

**Files:** `database/migrations/` (all files)  
**Fix:** Implement a migration runner with a `_migrations` tracking table. Apply files in sorted order.

---

# Summary Table of All CRITICAL Bugs

| ID | File | Line(s) | Bug | Impact |
|----|------|---------|-----|--------|
| C-01 | react_agent.py | 570-628, 842 | `_validate_arguments()` dead code — never called | Complete SSRF bypass |
| C-02 | pipeline_router.py | 36, 68 | `cache_mode` passed to functions without it | Pipeline crash |
| C-03 | session_store.py | 54-55 | Unbounded memory growth + no thread safety | OOM + data corruption |
| C-04 | auth_checkpoint.py | 46-62 | Plaintext credentials in DB | Credential leak |
| C-05 | tasks/base.py | 197 | `return` before `yield` in context manager | RuntimeError on cancel |
| C-06 | web_scanner.py | 289, 480 | requests.Session shared across 6 threads | Data corruption |
| C-07 | snapshot_manager.py | 165-181 | Non-serialization exceptions swallowed | Silent DB errors |
| C-08 | distributed_lock.py | 63-79 | Stale bound method on reconnect | Never reconnects |
| C-09 | health_monitor.py | 310-328 | DESC order wrong failure count | Broken health detection |
| C-10 | cache.py | 29-58 | Race on global Redis singleton | Connection leaks |
| C-11 | execution_engine.py | 61-74 | Scope bypass via positional args | Security bypass |
| C-12 | execution_engine.py | 124 | Kwargs silently dropped | Incorrect tool behavior |
| C-13 | event_stream.py | 232-236 | Events discarded after partial commit | Phantom data |
| C-14 | generate_tool_defs.py | 78-81 | Unescaped quotes in generated code | Worker crash on startup |
| C-15 | html_report.py | 293-298 | Stored XSS in remediation text | RCE in report viewer |

---

# SECOND SWEEP — Additional Findings

**Date:** 2026-06-17 (Second Pass)  
**Scope:** Deeper analysis: web_scanner_checks, database, config, TypeScript/TUI, templates, tests, Docker, CI, remaining Python modules  
**New findings:** 4 CRITICAL, 8 HIGH, ~60 MEDIUM, ~40 LOW/INFO

---

# CRITICAL (Second Sweep)

---

## C2-01: Destructive SQLi Payloads Executed Against Target — Scanner Is Attack Vector

**Files:** `tools/web_scanner_checks/injection_check.py:21-29`, `web_scanner_checks/response_check.py:17-22`, `web_scanner_checks/payloads/sqli_payloads.py:32-38`  
**Type:** Destructive Payload / Safety

### Bug
The scanner sends destructive SQLi payloads including `'; DROP TABLE users--`, `'; INSERT INTO users VALUES(1,'admin','password')--`, `"' INTO OUTFILE '/tmp/evil.txt'--"`, and `"' UNION SELECT LOAD_FILE('/etc/passwd')--"`. If the target is vulnerable, these payloads **actually execute** — dropping tables, inserting admin users, or writing files to the server. The scanner itself becomes the attack vector.

The WAF trigger payloads (response_check.py:17-22) also include actual SQLi: `' OR 1=1--` and ` UNION SELECT * FROM users--`.

### Impact
Destructive data loss, privilege escalation via admin user creation, file write to server. A production safety incident waiting to happen.

### Fix
Replace destructive payloads with read-only equivalents:
```python
# Replace dangerous payloads
"'; DROP TABLE users--" → "' UNION SELECT 1,1,1--"  # Read-only
"'; INSERT INTO users..." → "' AND 1=1--"           # Non-destructive
"' OR 1=1--" → "' OR 'test'='test"                  # WAF trigger, non-destructive
```

---

## C2-02: Session Fixation Check Uses Failed Login — 100% False Positives

**Files:** `tools/web_scanner_checks/auth_check.py:130-137`  
**Type:** Logic Error

### Bug
The session fixation check sends `{"username": "admin", "password": "wrong_pass_xyz"}` — credentials **guaranteed to fail**. By definition, failed logins never rotate session cookies. The test ALWAYS finds the cookie unchanged, producing 100% false-positive findings for session fixation on every endpoint.

```python
# Always sends WRONG password:
data={"username": "admin", "password": "wrong_pass_xyz"},
# Then checks if cookie changed — it NEVER does for failed login
```

### Impact
Every tested auth endpoint is reported as vulnerable to session fixation. Analysts waste effort investigating non-existent vulnerabilities; scanner credibility degraded.

### Fix
The check must use SUCCESSFUL credentials or at minimum attempt a realistic login:
```python
for username, password in DEFAULT_CREDS:
    login_resp = safe_request("POST", url, session, ...,
        data={"username": username, "password": password},
        allow_redirects=False)
    if login_resp and login_resp.status_code in (200, 302):
        post_cookies = {c.name: c.value for c in session.cookies}
        if post_value and post_value == pre_value:
            findings.append(...)
```

---

## C2-03: ConfigCheck and HeadersCheck Are Exact Duplicates — Double Findings, Double Requests

**Files:** `tools/web_scanner_checks/config_check.py` (entire 120 lines), `headers_check.py` (entire 175 lines)  
**Type:** Duplicate Code / Resource Waste

### Bug
These two files are functionally identical — both check the same security headers (exact same 7-headers list), CSP, cookies, and CORS with identical logic. The auto-discoverer in `__init__.py` registers BOTH, causing every security header issue to be reported TWICE and every check to issue two HTTP requests.

### Impact
Doubles network traffic, findings, and scan time. Security teams waste time deduplicating. WAF/IDS alerted twice as much.

### Fix
Delete `headers_check.py` and remove from `_skip_modules` or vice versa.

---

## C2-04: Docker SHA256 Hash Reused Across Three Unrelated Images — Supply-Chain Broken

**Files:** `argus-workers/Dockerfile:2`, `docker-compose.yml:19,49`  
**Type:** Supply-Chain Security

### Bug
The SHA256 digest `3b5425af5eb30e2753a40a3c2cf1e22a7b4a20335a80b0e24b05bfca01b290ef` is identically reused for three completely different images: `python:3.11-slim-bookworm`, `pgvector/pgvector:0.7.4-pg16`, and `redis:7-alpine`. This is a copy-paste error. The pgvector and Redis images are not verified against their actual digests — supply-chain integrity is broken.

### Impact
If someone publishes a tampered image tagged as `redis:7-alpine`, Docker will silently accept it because the SHA doesn't match.

### Fix
Generate and pin the correct SHA256 digest for each image individually:
```yaml
image: pgvector/pgvector:0.7.4-pg16@sha256:<ACTUAL_PGVECTOR_SHA>
image: redis:7-alpine@sha256:<ACTUAL_REDIS_SHA>
```

---

# CRITICAL (Second Sweep — TypeScript/TUI)

---

## C2-05: Path Traversal Check Broken on Windows — All Evidence Blocks

**Files:** `Argus-Tui/.../tui/routes/evidence-viewer.tsx:106-108`  
**Type:** CWE-22 Path Traversal / Platform Bug

### Bug
The path traversal check uses `resolvedPath.startsWith(baseDir + "/")` with a hardcoded forward slash. On Windows, `realpathSync()` returns backslash-separated paths (e.g., `C:\Users\.argus\...`). The string `baseDir + "/"` produces `C:\Users\.argus\artifacts/` which never matches a backslash path.

### Impact
On Windows, ALL evidence viewing is blocked with "Security: Invalid artifact path". On Linux, symlink attacks can still bypass since only path start is checked.

### Fix
```typescript
import { sep } from "path"
const resolvedNorm = resolvedReal.replace(/\\/g, '/')
const baseNorm = baseDirReal.replace(/\\/g, '/') + '/'
if (!resolvedNorm.startsWith(baseNorm)) { ... }
```

---

## C2-06: `execSync` Command Injection in Doctor Toolchain Check

**Files:** `Argus-Tui/.../commands/doctor.ts:392-393`  
**Type:** CWE-78 OS Command Injection

### Bug
`execSync(versionDef.version_cmd + " 2>&1", ...)` with a string argument implicitly uses `shell: true`, invoking the system shell. `version_cmd` is read from YAML definitions. An attacker who can modify `tool-definitions.yaml` can inject arbitrary commands.

### Impact
Arbitrary command execution on any machine running `argus doctor`.

### Fix
```typescript
const parts = versionDef.version_cmd!.split(/\s+/)
execFileSync(parts[0], [...parts.slice(1), "2>&1"], { ... })
```

---

## C2-07: Unhandled Promise Rejection in MCP stdin Write

**Files:** `Argus-Tui/.../bridge/mcp-client.ts:276`  
**Type:** CWE-248 Uncaught Exception

### Bug
If the child process has exited between the exit check and the write, `stdin.write()` throws synchronously with no try-catch. The `pending` Map entry is never cleaned up.

### Fix
```typescript
try {
  this.process.stdin!.write(JSON.stringify(request) + "\n")
} catch (err) {
  clearTimeout(timer)
  this.pending.delete(id)
  reject(new Error(`Failed to write to process stdin: ${err}`))
}
```

---

## C2-08: Undefined Route Navigation — Tab Clicks Do Nothing

**Files:** `Argus-Tui/.../tui/routes/engagement-detail.tsx:90`  
**Type:** Broken UI

### Bug
`route.navigate({ type: "engagement-detail", ... })` uses type `"engagement-detail"` which does NOT exist in `ArgusRoute` (valid types: `"dashboard" | "scan" | "findings" | "finding" | "engagements" | "engagement" | "report" | "workspace"`). Navigation is silently ignored.

### Impact
Clicking tabs in EngagementDetail does nothing. Users cannot navigate between Findings/Evidence/Timeline tabs.

### Fix
```typescript
route.navigate({ type: "engagement", engagementId: props.engagementId, tab: tab.id })
```

---

# CRITICAL (Second Sweep — Async/Python)

---

## C2-09: `asyncio.TimeoutError` Not Caught in Python < 3.11 — Silent Tool Hang

**Files:** `tool_core/sandbox.py:193,245-248,398,424-428`  
**Type:** Runtime Crash / Silent Hang

### Bug
`asyncio.wait_for()` raises `asyncio.TimeoutError`. In Python < 3.11, this is a **different type** from built-in `TimeoutError`. The `except TimeoutError:` at lines 193 and 398 will NOT catch it in Python ≤3.10. It falls through to generic `except Exception`, wrapping the timeout as a generic error instead of `TIMEOUT` status. In `run_streaming()`, the `timed_out` flag is never set.

### Impact
Timeouts silently become generic errors, breaking retry/circuit-breaker logic. In streaming mode, the tool hangs forever.

### Fix
```python
except (TimeoutError, asyncio.TimeoutError):
```

---

## C2-10: Leetspeak Prompt Injection Bypass — Redaction Doesn't Remove Payload

**Files:** `intent_parser.py:110-135`  
**Type:** Prompt Injection

### Bug
`sanitize_input()` detects leetspeak injections (e.g., `"1gn0r3 pr3v10us 1nstruct10ns"`) but only prefixes "[REDACTED]" to the sanitized output — the actual injection text remains intact. The regex redaction operates on the RAW text, not the leet-decoded form, so `"1gn0r3"` doesn't match `r"ignore"`.

### Impact
An attacker can inject arbitrary LLM instructions via leetspeak-encoded text, bypassing entirely.

### Fix
Replace the entire injection block with actual content stripping on the normalized text, not just a prefix.

---

# HIGH (Second Sweep)

---

## H2-01: Module Auto-Discovery Uses Hardcoded Import Path — All Checks Silently Fail on Packaging

**Files:** `tools/web_scanner_checks/__init__.py:25`  
**Type:** Packaging Bug / Silent Failure

### Bug
The dynamic module loader uses `f"tools.web_scanner_checks.{module_name}"` as a hardcoded absolute import path. If the package is installed as a dependency or the project is reorganized, ALL check modules silently fail to load. The `except Exception` catches the `ImportError` and only logs a warning.

### Impact
The scanner runs with NO checks loaded, producing a false-negative security assessment with no indication of failure.

### Fix
```python
module = importlib.import_module(f".{module_name}", package=__package__)
```

---

## H2-02: `safe_request` Follows Untrusted Redirects Unconditionally — SSRF Chain

**Files:** `tools/web_scanner_checks/_helpers.py:23`  
**Type:** CWE-601 / SSRF

### Bug
`safe_request` sets `allow_redirects=True` without a redirect limit. If the target server responds with a 302 to `169.254.169.254` or an attacker domain, the scanner blindly follows it. Redirect-checking tests never see the 302 Location header because the redirect was already followed.

### Impact
SSRF amplification — attacker-controlled redirect leads to internal network scanning. Missed open redirect detections.

### Fix
```python
kwargs.setdefault("allow_redirects", False)
resp = session.request(method, url, **kwargs)
# Handle manually with max 3 hops
```

---

## H2-03: Cookie Parsing Broken on `Expires` Date — Commas in Values Cause Split

**Files:** `tools/web_scanner_checks/config_check.py:72`, `headers_check.py:99`  
**Type:** Broken Detection

### Bug
`cookie_header.split(",")` splits on ALL commas, but `Set-Cookie` values legitimately contain commas in the `Expires` attribute (e.g., `Expires=Wed, 21 Oct 2025`). Every cookie with an expiry date is split into multiple segments; neither contains HttpOnly/Secure/SameSite, so BOTH segments are flagged as insecure — double false positives per cookie.

### Impact
Every cookie with an expiry date produces double false-positive findings. Virtually all session cookies have expiry dates.

### Fix
Use proper cookie parsing:
```python
from http.cookies import SimpleCookie
cookies = SimpleCookie()
cookies.load(cookie_header)
for key, morsel in cookies.items():
    if not morsel.get("httponly"):
        issues.append("Missing HttpOnly")
```

---

## H2-04: Injection Testing Only Scans HTML Parameters — Misses All Headless APIs

**Files:** `tools/web_scanner_checks/injection_check.py:107-114`  
**Type:** False Negative

### Bug
`_find_params` extracts URL parameters from HTML response text using regex `[?&](\w+)=`. Modern SPAs, GraphQL endpoints, and JSON APIs don't embed parameters in HTML. The injection checker finds zero params, skips all injection tests, and reports no findings. POST body parameters are entirely ignored.

### Impact
Entire injection detection suite (SQLi, XSS, SSTI, LFI, CMDI) is non-functional for modern applications.

### Fix
Always include common parameter names:
```python
COMMON_PARAMS = ["id", "page", "file", "name", "user", "search", "q", "url", "redirect", "path"]
def _find_params(target_url, session):
    params = set()
    resp = safe_request(...)
    if resp:
        params = set(re.findall(r'[?&](\w+)=', resp.text))
    params.update(COMMON_PARAMS)
    return params
```

---

## H2-05: Boolean SQLi Baseline Comparison Compares Wrong Values

**Files:** `tools/web_scanner_checks/injection_check.py:133-151`  
**Type:** Logic Error

### Bug
`_check_boolean_sqli` compares `false_resp.text != baseline` to verify the false condition produces a different result. But `false_url` adds `?param=1' AND '1'='2` which is fundamentally different from the baseline URL (which has different/no parameters). The comparison should be `true_resp.text == baseline` and `false_resp.text != baseline`.

### Fix
Compare true vs false responses, not vs baseline:
```python
if true_resp.text != false_resp.text:
    # Potential boolean-based injection
```

---

## H2-06: Cache Poisoning Check Has Inverted Logic

**Files:** `tools/web_scanner_checks/network_check.py:56-59`  
**Type:** Logic Error

### Bug
The code returns early if `not cache_control and not expires` — meaning "no caching headers = not checking". But absence of caching headers means the response IS cacheable by default. The check should be the opposite.

### Fix
```python
is_cacheable = "no-cache" not in cache_control and "no-store" not in cache_control
if is_cacheable and "127.0.0.1" in resp.text:
    findings.append(...)
```

---

## H2-07: `which` Command Fails on Windows — All Tools Reported Missing

**Files:** `Argus-Tui/.../commands/doctor.ts:385`  
**Type:** Platform Bug

### Bug
`execFileSync("which", [tool], ...)` — the `which` command is Unix-only. On Windows, this always throws, falsely reporting ALL core security tools as missing.

### Fix
```typescript
if (process.platform === "win32") {
  execFileSync("where", [tool], { stdio: "ignore" })
} else {
  execFileSync("which", [tool], { stdio: "ignore" })
}
```

---

## H2-08: `pip install --require-hashes` Silently Falls Back Without Verification

**Files:** `argus-workers/Dockerfile:40-41`  
**Type:** Supply-Chain Security

### Bug
```dockerfile
RUN pip install --no-cache-dir --require-hashes 2>/dev/null -r requirements.txt || \
    pip install --no-cache-dir -r requirements.txt
```
Two problems: (1) `2>/dev/null` silently discards hash errors; (2) the `||` fallback runs pip WITHOUT `--require-hashes`. Since requirements.txt doesn't contain hashes, the first command always fails and the fallback installs everything without verification.

### Fix
```dockerfile
RUN pip install --no-cache-dir -r requirements.txt
```

---

## H2-09: Pre-commit Ruff Hooks Never Match Any Files

**Files:** `argus-workers/.pre-commit-config.yaml:10,12`  
**Type:** CI Reliability

### Bug
```yaml
files: ^argus-workers/.*\.py$
```
The pre-commit config is inside `argus-workers/`. File paths relative to the hook's working directory are just `*.py` — the `^argus-workers/` prefix will never match. Ruff and ruff-format **never run**.

### Fix
```yaml
files: \.py$
```
Or move `.pre-commit-config.yaml` to the repo root.

---

## H2-10: `Verified = TRUE` Always Set — Even for False Positives

**Files:** `models/feedback.py:131-134`  
**Type:** Data Integrity

### Bug
The UPDATE always sets `verified = TRUE`, regardless of whether the analyst marked it as true positive OR false positive. "Verified" should mean "confirmed vulnerability", but here it means "analyst reviewed" — conflating two semantics.

### Impact
Downstream queries and UIs that rely on `verified = TRUE` to mean "confirmed vulnerability" show false positives as confirmed.

### Fix
```sql
SET verified = %s  -- use feedback.is_true_positive
```
Or add a separate `reviewed` column.

---

## H2-11: No Transactional Boundary in Feedback Loop — Partial Updates

**Files:** `models/feedback.py:81-148`  
**Type:** Data Integrity

### Bug
`_store_feedback()`, `_update_finding()`, `_get_finding_source_tool()`, `_get_finding_org_id()` each create their own independent database connection via `get_db().get_connection()`. If `_store_feedback` commits successfully but `_update_finding` fails, the feedback is stored but the finding is NOT updated — data integrity violation.

### Fix
Pass a shared connection/cursor to all internal methods within a single transaction.

---

# MEDIUM (Second Sweep — Selected)

| ID | File | Bug | Fix |
|----|------|-----|-----|
| M2-01 | web_scanner_checks/detection_check.py:149-158 | OPTIONS 200 flagged as verb tampering (FP) | Remove OPTIONS or check Allow header |
| M2-02 | web_scanner_checks/payloads/lfi_payloads.py:21 | Null byte is literal `\x00`, not actual null | Use `%00` |
| M2-03 | web_scanner_checks/_helpers.py:112-168 | JWT test only checks `alg: none`, misses RS→HS256 attack | Add RS256→HS256 test |
| M2-04 | web_scanner_checks/ssl_check.py:181,196-198 | Late imports inside method body | Move to module top |
| M2-05 | web_scanner_checks/graphql_check.py:42-44 | URL construction drops path components | Use proper urljoin |
| M2-06 | database/connection.py:217-218 | `notify()` instead of `notify_all()` on pool condition | Use `notify_all()` |
| M2-07 | database/repositories/base.py:397-409 | SQL f-string in `update_by_id` bypasses psycopg2.sql.Identifier | Use `SQL().format(Identifier())` |
| M2-08 | database/settings_repository.py:66-89 | API keys stored in plaintext | Encrypt with Fernet |
| M2-09 | llm_client.py:332-355 | Blocking Redis calls in async code | Use `redis.asyncio` |
| M2-10 | llm_client.py:167-188 | Cross-tenant API key leakage when user_email unset | Remove unscoped fallback |
| M2-11 | embedding_service.py:88-92 | Class-level cooldown flag shared across all instances | Make instance-level |
| M2-12 | TUI/.../workflow-runner.ts:90 vs 373 | Low-severity count mismatch between summary and return | Use same threshold |
| M2-13 | TUI/.../planner/planner.ts:77-80 | Silent phase skipping when zero tools available | Always emit warning |
| M2-14 | TUI/.../workflows/*.yaml | SAST tools selected for web assessments (supports_web=false ignored) | Filter by targetType |
| M2-15 | tasks/scheduled.py:255-258 | Cron expression hardcoded, ignores configured schedule | Use dynamic cron value |
| M2-16 | tasks/replay.py:38 | Replayed task ID modified, breaks traceability | Preserve original task ID |
| M2-17 | models/confidence_scorer.py:125 | `cvss_score = 0.0` treated as "not set" | Use `finding.get("cvss_score", 0)` |
| M2-18 | models/finding.py:19-24 | `EvidenceStrength` enum missing `NONE` variant | Add `NONE = "NONE"` |
| M2-19 | tools/scope_validator.py:132 | Wildcard domain dot count check treats all TLDs equally | Check suffix only |
| M2-20 | compliance_posture_scorer.py:176 | `total_findings` inflated per framework | Count only mapped findings |
| M2-21 | orchestator_pkg/recon_context_service.py:32 | "flask" mapped to "Django" framework | Fix to "Flask" |
| M2-22 | orchestator_pkg/persistence/finding_persistence_service.py:264-282 | Non-secret HIGH findings never trigger webhooks (dead code) | Fix batch save ID return |
| M2-23 | TUI/.../workflows/browser_assessment.yaml | Phase requires `content_discovery` + `browser_verification` — no tool has both | Split phase |

---

# Summary Table — New CRITICAL Bugs (Second Sweep)

| ID | File | Line(s) | Bug | Impact |
|----|------|---------|-----|--------|
| C2-01 | web_scanner_checks/ | injection:21-29, sqli:32-38 | Destructive SQLi payloads executed on target | Scanner = attack vector |
| C2-02 | web_scanner_checks/auth_check.py | 130-137 | Session fixation uses failed login | 100% false positives |
| C2-03 | config_check.py / headers_check.py | Full files | Exact duplicate files | Double findings/requests |
| C2-04 | Dockerfile, docker-compose.yml | 2, 19, 49 | SHA256 hash reused across 3 different images | Supply-chain broken |
| C2-05 | TUI/evidence-viewer.tsx | 106-108 | Path traversal check broken on Windows | All evidence blocked |
| C2-06 | TUI/doctor.ts | 392-393 | execSync command injection | RCE via YAML |
| C2-07 | TUI/mcp-client.ts | 276 | Unhandled promise rejection in stdin write | Leaked pending requests |
| C2-08 | TUI/engagement-detail.tsx | 90 | Undefined route navigation | Tab clicks do nothing |
| C2-09 | sandbox.py | 193, 398 | `asyncio.TimeoutError` not caught in Python<3.11 | Silent tool hang |
| C2-10 | intent_parser.py | 110-135 | Leetspeak prompt injection bypass | LLM instruction compromise |

---

# Fix Progress Summary

**Last updated:** 2026-06-17  
**Total findings:** ~200+ across all sweeps

---

## Priority Tiers

| Tier | Criteria | Count | Action |
|------|----------|-------|--------|
| **P0** | Immediate — data loss, security bypass, crash | 25 | Fix before next deployment |
| **P1** | This sprint — incorrect results, resource leaks, limited exploits | ~30 | Fix within current sprint |
| **P2** | Next sprint — correctness, reliability, edge cases | ~60 | Schedule for next sprint |
| **P3** | Backlog — hardening, best practices, minor issues | ~85 | Fix when time permits |

---

## CRITICAL Fix Progress

| ID | Description | Status | Assigned | Notes |
|----|-------------|--------|----------|-------|
| C-01 | LLM scope validation dead code — SSRF bypass | ✅ Fixed | — | Wired `_validate_arguments()` into `run()` |
| C-02 | `cache_mode` passed to functions without it | ✅ Fixed | — | pipelines pass it; recon/scan accept it |
| C-03 | AgentSessionStore memory growth + no thread safety | ✅ Fixed | — | Added lock + TTL eviction + background eviction loop |
| C-04 | Plaintext credentials in DB | ✅ Fixed | — | Encrypted with Fernet in auth_checkpoint |
| C-05 | `return` before `yield` in context manager | ✅ Fixed | — | Replaced with `raise OperatorCanceled` |
| C-06 | requests.Session shared across 6 threads | 🔴 Pending | — | Use thread-local sessions (complex — defer to P1) |
| C-07 | Non-serialization exceptions swallowed in retry loop | ✅ Fixed | — | Non-serialization errors now re-raised immediately |
| C-08 | Stale bound method on Redis reconnect | ✅ Fixed | — | Uses method_name string, re-binds on retry |
| C-09 | DESC order wrong failure count in health monitor | ✅ Fixed | — | Break on first success (newest-first) |
| C-10 | Race on global Redis singleton | ✅ Fixed | — | Added threading lock |
| C-11 | Scope bypass via positional args | ✅ Fixed | — | Args inspected in scope middleware |
| C-12 | Kwargs silently dropped in execution engine | ✅ Fixed | — | kwargs forwarded to tool_runner.run() |
| C-13 | Events discarded after partial DB commit | ✅ Fixed | — | Added `mark_committed()` + `_committed` flag |
| C-14 | Unescaped quotes in generated Python code | ✅ Fixed | — | Uses json.dumps() for defaults |
| C-15 | Stored XSS in HTML report remediation text | ✅ Fixed | — | Uses json.dumps() for JS-safe embedding |
| C2-01 | Destructive SQLi payloads on target | ✅ Fixed | — | Replaced DROP/INSERT/OUTFILE with read-only |
| C2-02 | Session fixation 100% false positives | ✅ Fixed | — | Now tries actual login with default creds |
| C2-03 | Duplicate config_check.py / headers_check.py | ✅ Fixed | — | `headers_check` added to skip list |
| C2-04 | SHA256 hash reused across 3 different images | ✅ Fixed | — | Removed incorrect SHAs from pgvector/redis |
| C2-05 | Path traversal check broken on Windows | ✅ Fixed | — | Normalizes path separators before comparison |
| C2-06 | execSync command injection in doctor | ✅ Fixed | — | Uses execFileSync with args array |
| C2-07 | Unhandled promise rejection in MCP stdin | ✅ Fixed | — | Wrapped in try-catch with cleanup |
| C2-08 | Undefined route navigation — tabs do nothing | ✅ Fixed | — | Changed to valid route type "engagement" |
| C2-09 | asyncio.TimeoutError not caught in Python<3.11 | ✅ Fixed | — | Catches both TimeoutError types |
| C2-10 | Leetspeak prompt injection bypass | ✅ Fixed | — | Strips matched content instead of prefixing |

---

## HIGH Fix Progress

| ID | Description | Status | Assigned | Notes |
|----|-------------|--------|----------|-------|
| H-01 | Prompt injection via tool output | 🟡 Pending | — | Base64-encode tool output |
| H-02 | Circuit breaker threshold = 1 | 🟡 Pending | — | Change to 5+ |
| H-03 | `memory_context` unsanitized | 🟡 Pending | — | Add sanitize_for_llm() |
| H-04 | WebSocket Redis connection not thread-safe | 🟡 Pending | — | Add lock + reconnect logic |
| H-05 | `_rt_emitted_fingerprints` memory growth | 🟡 Pending | — | Use LRU cache |
| H-06 | Fingerprint dedup TOCTOU race | 🟡 Pending | — | Atomic check-and-add |
| H-07 | Silent data loss when all saves fail | 🟡 Pending | — | Raise if all fails |
| H-08 | Variable shadowing loses findings on fallback | 🟡 Pending | — | Change `=` to `.extend()` |
| H-09 | DLQ error_message not redacted | 🟡 Pending | — | Apply redaction patterns |
| H-10 | SIGALRM leaks TCP connections | 🟡 Pending | — | Replace with HTTP timeouts |
| H-11 | Unvalidated vulnerability type strings | 🟡 Pending | — | Add KnownVulnType enum |
| H-12 | REDIS_URL logged with credentials | 🟡 Pending | — | Move to lazy init |
| H-13 | CWE list crashes normalizer | 🟡 Pending | — | Handle list type for cwe |
| H-14 | Parameter discovery/fuzzing race | 🟡 Pending | — | Run discovery first, then fuzzing |
| H-15 | Connection leak on cursor() failure | 🟡 Pending | — | Move cursor() into try block |
| H-16 | Evidence sanitization silent fallback | 🟡 Pending | — | Remove bare except |
| H-17 | reset_tenant_context() returns NULL | 🟡 Pending | — | Use sentinel UUID |
| H-18 | Event listener leak in Playwright scan | 🟡 Pending | — | Remove listeners between iterations |
| H-19 | Duplicate risk check (already fixed) | ✅ Fixed | — | Duplicate block removed |
| H-20 | Swarm agents lack scope validation | 🟡 Pending | — | Add validate_target_scope() |
| H2-01 | Hardcoded import path breaks on packaging | 🟡 Pending | — | Use relative import |
| H2-02 | Unconditional redirect following → SSRF | 🟡 Pending | — | Set allow_redirects=False |
| H2-03 | Cookie parsing broken on Expires commas | 🟡 Pending | — | Use SimpleCookie |
| H2-04 | Injection tests miss headless APIs | 🟡 Pending | — | Add common params fallback |
| H2-05 | Boolean SQLi compares wrong baselines | 🟡 Pending | — | Compare true vs false responses |
| H2-06 | Cache poisoning check logic inverted | 🟡 Pending | — | Check cacheability correctly |
| H2-07 | `which` fails on Windows | 🟡 Pending | — | Use `where` on Windows |
| H2-08 | pip --require-hashes silent fallback | 🟡 Pending | — | Remove broken fallback |
| H2-09 | Pre-commit ruff hooks never match | 🟡 Pending | — | Fix regex pattern |
| H2-10 | `verified = TRUE` always for false positives | 🟡 Pending | — | Use is_true_positive field |
| H2-11 | No transactional boundary in feedback | 🟡 Pending | — | Share connection across operations |

---

## MEDIUM Fix Progress (Summary)

| Count | Status | Notes |
|-------|--------|-------|
| 40 | 🟡 Pending | See body of report for individual fixes |
| 0 | ✅ Fixed | No MEDIUM bugs marked fixed yet |

---

## LOW/INFO Fix Progress (Summary)

| Count | Status | Notes |
|-------|--------|-------|
| 75 | ⚪ Pending | Hardening and best-practice improvements |
| 0 | ✅ Fixed | No LOW/INFO items marked fixed yet |

---

## Fix Status Legend

| Icon | Meaning |
|------|---------|
| 🔴 Pending | Not yet started — critical priority |
| 🟡 Pending | Not yet started — high/medium priority |
| ⚪ Pending | Not yet started — low priority |
| 🔵 In Progress | Being actively worked on |
| ✅ Fixed | Fix verified and merged |
| ❌ Won't Fix | Decision made not to address |

---

*Report generated 2026-06-17 by automated codebase audit. Last updated: 2026-06-17 after second sweep.*
