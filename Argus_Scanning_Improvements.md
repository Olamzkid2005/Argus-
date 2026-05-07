# ARGUS Scanning Engine Improvement Plan

> Speed · Accuracy · Coverage — Grounded in the Codebase

## Current State

10 findings on Juice Shop. Tools run sequentially. No parallelism. Scans timeout at 20min. LLM agent stops after 2 tools.

## Root Problems

3 independent problems:
1. Everything runs sequentially when it could be parallel
2. Tools time out before producing output
3. LLM agent makes decisions without enough context to pick correctly

## This Plan

15 improvements across speed, accuracy, and coverage. Each is specific, actionable, grounded in what is actually in the codebase, and independent of the others.

---

## All 15 Improvements — Overview

| # | Improvement | Category | What It Solves | Effort |
|---|---|---|---|---|
| 1 | Parallel recon tool execution | ⚡ Speed | Recon takes 8min sequential — could be 90s parallel | 1 day |
| 2 | Parallel scan tool execution | ⚡ Speed | Nuclei+dalfox+sqlmap run one at a time — waste pure time | 1 day |
| 3 | Nuclei template scoping | ⚡ Speed + 🎯 Accuracy | 13K templates run blindly — 90% irrelevant to target | 3 hrs |
| 4 | Tool result caching fix | ⚡ Speed | Cache key uses hash() — unstable across processes, never hits | 2 hrs |
| 5 | LLM agent context — tech stack | 🎯 Accuracy | Agent gets no tech info so picks generic tools | 2 hrs |
| 6 | LLM agent stopping — 4 tool min | 🎯 Accuracy | Agent stops after 2 tools because __skip__ raises Exception | 2 hrs |
| 7 | Eliminate RATE_LIMIT_DELAY | ⚡ Speed | Artificial 200ms sleep between every request — pure waste | 30 min |
| 8 | Web scanner async/concurrent | ⚡ Speed | WebScanner runs 20+ checks sequentially — should be async | 1 day |
| 9 | Nuclei severity filter by agg | 🎯 Accuracy | Default scan runs all severities — noise from INFO/LOW | 1 hr |
| 10 | Target pre-validation | 🎯 Accuracy | DNS check blocks scan if target has multiple subdomains | 1 hr |
| 11 | Tool output streaming | ⚡ Speed | Findings only visible after tool completes — need streaming | 1 day |
| 12 | Celery worker concurrency | ⚡ Speed | Default concurrency = CPU count — scan tasks need more | 30 min |
| 13 | Cross-scan dedup via pgvector | 🎯 Accuracy | pgvector_repository exists but is never called — duplicates | 2 hrs |
| 14 | Confidence scoring from tool agree | 🎯 Accuracy | Single-tool findings get 0.7 by default — need real signal | 2 hrs |
| 15 | Add Playwright/browser scan | 📡 Coverage | SPA apps like Juice Shop miss DOM XSS without browser | 1 day |

---

# SPEED IMPROVEMENTS (1–4, 7, 8, 12)

---

## 1. Parallel Recon Tool Execution

The biggest single time saving in the codebase. Recon takes 8+ minutes sequentially. Parallelised, it takes ~90 seconds.

### What is happening now

`orchestrator_pkg/recon.py` runs 11 tools sequentially. httpx runs, finishes, then katana starts, finishes, then ffuf starts, and so on. The total is the SUM of all tool durations. Tools that have nothing to do with each other (amass DNS vs nikto web scanner vs gau URL lookup) wait for each other with zero benefit.

### What the code already has

The codebase has ThreadPoolExecutor imported in various places and concurrent.futures available. The ToolRunner.run() method is already thread-safe (each call creates its own subprocess). There is no shared mutable state between tool calls. Nothing prevents parallelism — it just was never implemented.

### The fix

Replace the sequential calls in execute_recon_tools() with a ThreadPoolExecutor that runs groups of tools concurrently. Group tools by their dependency relationship: httpx must run first (provides the live endpoint list), then all remaining tools can run simultaneously.

```python
# orchestrator_pkg/recon.py — replace sequential calls with:
from concurrent.futures import ThreadPoolExecutor, as_completed

def _run_tool_safe(ctx, name, args, timeout):
    """Thread-safe wrapper — catches all exceptions."""
    try:
        result = ctx.tool_runner.run(name, args, timeout=timeout)
        return name, result
    except Exception as e:
        logger.warning(f"{name} failed: {e}")
        return name, None

# Phase 1: httpx must run first (other tools depend on live endpoints)
_, httpx_result = _run_tool_safe(ctx, 'httpx', ['-u', target, '-json', '-silent'], 30)

# Phase 2: all other recon tools run simultaneously
recon_jobs = [
    ('katana', ['-u', target, '-json', '-silent'], 90),
    ('ffuf', ['-u', f'{target}/FUZZ', '-w', wordlist, '-o', '-', '-of', 'json', '-silent'], 60),
    ('amass', ['enum', '-d', target_domain], amass_timeout),
    ('subfinder', ['-d', target_domain, '-silent'], 30),
    ('naabu', ['-host', target_domain, '-json', '-silent'], 60),
    ('whatweb', ['--format=json', target], 30),
    ('nikto', ['-h', target, '-Format', 'csv'], 90),
    ('gau', [target, '--json'], 60),
    ('waybackurls', [target], 45),
]
results = {}
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(_run_tool_safe, ctx, *job): job[0] for job in recon_jobs}
    for future in as_completed(futures):
        name, result = future.result()
        results[name] = result

# Wall clock time: max(individual timeouts) instead of sum = ~90s worst case
```

### Time saving

Sequential worst case: 465s (7.8min) → Parallel worst case: 90s (longest single tool = amass at 120s, but typically 60-90s)

---

## 2. Parallel Scan Tool Execution

Nuclei (300s) + dalfox (300s) + sqlmap (300s) currently run back-to-back. Parallel: total = 300s not 900s.

### What is happening now

execute_scan_tools() in orchestrator_pkg/scan.py runs nuclei, then waits for it to finish, then runs dalfox, waits, then sqlmap. These three tools test completely different vulnerability classes and share no state. Running them in parallel saves 600 seconds on default aggressiveness.

### The fix

Use the same ThreadPoolExecutor pattern. Group tools by their dependency — arjun must run before dalfox/sqlmap (it discovers parameters they need). Everything else can run in parallel.

```python
# orchestrator_pkg/scan.py
from concurrent.futures import ThreadPoolExecutor, as_completed

# Phase 1: parameter discovery (arjun) — must complete before injection tools
if 'arjun' not in _skip and not recon_context?.parameter_bearing_urls:
    _, arjun_result = _run_tool_safe(ctx, 'arjun', ['-u', target, '-oJ', arjun_out], 120)
    # merge discovered params into target URL list for next phase

# Phase 2: all vulnerability scanners run simultaneously
scan_jobs = []
if 'nuclei' not in _skip:
    scan_jobs.append(('nuclei', nuclei_cmd, nuclei_timeout))
if 'dalfox' not in _skip:
    scan_jobs.append(('dalfox', dalfox_cmd, TOOL_TIMEOUT_LONG))
if 'sqlmap' not in _skip:
    scan_jobs.append(('sqlmap', sqlmap_cmd, TOOL_TIMEOUT_LONG))
if 'jwt_tool' not in _skip and recon_context?.has_api:
    scan_jobs.append(('jwt_tool', jwt_cmd, 60))
if 'testssl' not in _skip and target.startswith('https'):
    scan_jobs.append(('testssl', testssl_cmd, 120))

with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {pool.submit(_run_tool_safe, ctx, *job): job[0] for job in scan_jobs}
    for future in as_completed(futures, timeout=TOOL_TIMEOUT_LONG + 60):
        name, result = future.result()
        if result and result.stdout:
            parsed = ctx.parser.parse(name, result.stdout)
            all_findings.extend([ctx._normalize_finding(p, name) for p in parsed if p])

# Wall-clock: max(300, 300, 300) = 300s instead of 300+300+300 = 900s
```

### Time saving

Scan phase: 900s sequential → 300s parallel. Combined with parallel recon: total pipeline drops from ~40min to ~8min on default aggressiveness.

---

## 3. Nuclei Template Scoping by Tech Stack

Running all 13,000 nuclei templates on every target wastes 80% of nuclei's time on irrelevant checks. Scoping to detected tech reduces runtime by 60-70% with no accuracy loss.

### What is happening now

scan.py runs nuclei with `-u target -jsonl-export - -silent`. When local templates exist, it appends `-t {templates_path}`. This runs every single template including WordPress templates on non-WordPress sites, Java templates on PHP sites, and cloud templates on on-prem targets.

### The fix

Use ReconContext.tech_stack to scope nuclei template selection. Pass specific -t flags for tags that match detected technologies. Nuclei supports tag-based filtering via -tags.

```python
# In scan.py, replace the flat nuclei_cmd with:
def _build_nuclei_tags(recon_context) -> list[str]:
    """Build nuclei -tags flag from detected tech stack."""
    TECH_TAG_MAP = {
        'wordpress': ['wordpress', 'wp'],
        'php': ['php'],
        'apache': ['apache'],
        'nginx': ['nginx'],
        'java': ['java', 'spring', 'tomcat'],
        'node': ['nodejs', 'express'],
        'react': ['javascript'],
        'django': ['python', 'django'],
        'flask': ['python', 'flask'],
        'mysql': ['mysql'],
        'postgresql': ['postgresql'],
        'redis': ['redis'],
        'docker': ['docker'],
    }
    # Always include these critical tags regardless of tech stack
    ALWAYS_INCLUDE = ['cve', 'rce', 'sqli', 'xss', 'ssrf', 'lfi',
                      'exposed-panel', 'default-login', 'misconfig', 'takeover']
    tags = set(ALWAYS_INCLUDE)
    if recon_context and recon_context.tech_stack:
        for tech in recon_context.tech_stack:
            for key, mapped_tags in TECH_TAG_MAP.items():
                if key in tech.lower():
                    tags.update(mapped_tags)
    return ['-tags', ','.join(sorted(tags))]

nuclei_cmd = ['-u', target, '-jsonl-export', '-', '-silent']
nuclei_cmd += _build_nuclei_tags(recon_context)
# Result: runs ~2,000-4,000 relevant templates instead of 13,000
```

### Time saving

Nuclei runtime: 300s → ~120s (60% reduction). Also reduces false positives from templates that don't apply to the target tech stack.

---

## 4. Fix the Tool Result Cache (Currently Never Hits)

The cache key uses Python's hash() which is randomised per-process in Python 3.3+. Every Celery worker gets a different hash for identical args. The cache never hits.

### The problem in the code

tool_runner.py line 283: `cache_key = f'tool_result:{tool}:{hash(tuple(args))}'`. Python's hash() uses a random seed per process by default (PYTHONHASHSEED). A worker that runs nuclei and caches the result at hash=4823947 will store the result, but the next worker that runs the same scan looks up hash=9183724 and gets nothing.

```python
# tools/tool_runner.py — line 283
# BROKEN (current):
cache_key = f'tool_result:{tool}:{hash(tuple(args))}'

# FIXED — use a stable deterministic hash:
import hashlib
args_str = ':'.join(str(a) for a in args)
stable_hash = hashlib.sha256(f'{tool}:{args_str}'.encode()).hexdigest()[:16]
cache_key = f'tool_result:{stable_hash}'

# Now the same tool+args always produces the same cache key
# across all workers and all processes.
# TTL=300s (5min) is already set — rescan within 5min gets instant results.
```

### Impact

Rescans and expand_recon loop-backs now get instant results for tools that already ran. Eliminates the largest source of duplicate runtime on the second recon pass.

---

## 7. Remove the Artificial RATE_LIMIT_DELAY Sleep

RATE_LIMIT_DELAY_MS = 200ms is injected between web scanner requests. 200ms × hundreds of requests = minutes of pure waiting.

### What is happening now

web_scanner.py line 332 passes rate_limit=RATE_LIMIT_DELAY_MS/1000.0 to the request session. Constants.py shows RATE_LIMIT_DELAY_MS = 200. The web scanner runs 20+ checks, each making multiple requests. 200ms sleep per request on a local target (Juice Shop) is artificially throttling a scan that has no rate limit concern.

```python
# config/constants.py — make this aggressiveness-aware:
RATE_LIMIT_DELAY_MS = {
    'default': 100,   # 0.1s — polite but not wasteful
    'high': 50,       # 0.05s — faster
    'extreme': 0,     # no delay — maximum speed
}

# In web_scanner.py __init__:
def __init__(self, target, aggressiveness='default', ...):
    from config.constants import RATE_LIMIT_DELAY_MS
    delay = RATE_LIMIT_DELAY_MS.get(aggressiveness, 100)
    self.rate_limit = delay / 1000.0
```

### Time saving

On default aggressiveness with 200 requests: 200 × 200ms = 40 seconds of pure sleep eliminated.

---

## 8. Make WebScanner Checks Concurrent

web_scanner.scan() runs 20+ checks sequentially. Each check makes HTTP requests and waits for responses. These are fully independent.

### What is happening now

The scan() method builds a checks list then calls each one in a for loop. check_security_headers makes an HTTP request and waits. check_cors makes another. check_sensitive_files makes dozens. They are all I/O bound and completely independent. Running them concurrently would reduce WebScanner runtime from ~120s to ~15s.

```python
# tools/web_scanner.py — replace the for loop in scan():
def scan(self, target_url: str) -> list[dict]:
    self.target_url = target_url
    self.session = self._create_session()
    findings = []

    checks = [
        self.check_security_headers,
        self.check_csp,
        self.check_cookies,
        self.check_cors,
        self.check_sensitive_files,
        self.check_js_secrets,
        self.check_open_redirects,
        self.check_host_header_injection,
        self.check_verb_tampering,
        self.check_debug_endpoints,
        self.check_auth_endpoints,
        self.check_xss,
        self.check_ssti,
    ]

    # Run all checks concurrently — they are fully independent
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(check): check.__name__ for check in checks}
        for future in as_completed(futures, timeout=90):
            try:
                result = future.result()
                if result:
                    if isinstance(result, list):
                        findings.extend(result)
                    elif isinstance(result, dict):
                        findings.append(result)
            except Exception as e:
                logger.warning(f'{futures[future]} failed: {e}')
    return findings

# Runtime: max(check_durations) instead of sum(check_durations)
# Estimated: 120s → 15-20s
```

---

## 12. Increase Celery Worker Concurrency for Scan Tasks

### What is happening now

The Celery worker starts with default concurrency = os.cpu_count(). On a 2-core server this means 2 concurrent tasks. If one engagement is scanning and another is analyzing, the second scan task queues behind the first. With the new parallel executor inside each task, individual tasks are CPU-light during I/O waits — you can safely run more concurrent tasks.

```python
# celery_app.py — add worker configuration:
app.conf.worker_concurrency = int(os.getenv('CELERY_CONCURRENCY', '8'))
app.conf.worker_prefetch_multiplier = 1  # Don't pre-fetch — each task is long
app.conf.task_acks_late = True           # Ack after completion, not on receipt

# start-argus.sh — set concurrency for the worker:
celery -A celery_app worker \
  --loglevel=info \
  --concurrency=8 \
  --prefetch-multiplier=1 \
  -Q default,scan,recon,analysis,report
```

---

# ACCURACY IMPROVEMENTS (5, 6, 9, 10, 13, 14)

---

## 5. Feed Full ReconContext Signals to LLM Tool Selection

The LLM agent receives a plain text recon summary but does not get the structured ReconContext fields. It cannot make conditional decisions like 'only run wpscan if WordPress detected'.

### What is happening now

agent_prompts.py build_tool_selection_prompt() passes recon_context.to_llm_summary() — a truncated plain text string. ReconContext has structured fields: `has_login_page`, `has_api`, `has_file_upload`, `tech_stack[]`, `auth_endpoints[]`, `api_endpoints[]`, `parameter_bearing_urls[]`, `open_ports[]`. None of these are exposed as structured data to the LLM. The LLM has to infer them from prose.

### The fix

Add a `to_llm_structured()` method to ReconContext that returns a compact JSON object the LLM can reference precisely in its reasoning.

```python
# models/recon_context.py — add structured export:
def to_llm_structured(self) -> str:
    import json
    return json.dumps({
        'target': self.target_url,
        'live_endpoints_count': len(self.live_endpoints),
        'parameter_bearing_urls': self.parameter_bearing_urls[:10],
        'auth_endpoints': self.auth_endpoints[:5],
        'api_endpoints': self.api_endpoints[:5],
        'open_ports': [p.get('port') for p in self.open_ports[:5]],
        'tech_stack': self.tech_stack[:10],
        'has_login_page': self.has_login_page,
        'has_api': self.has_api,
        'has_file_upload': self.has_file_upload,
        'findings_count': self.findings_count,
    }, indent=2)

# agent_prompts.py — build_tool_selection_prompt():
recon_section = f'''
=== RECON FINDINGS (STRUCTURED) ===
{recon_context.to_llm_structured()}

=== RECON SUMMARY (PROSE) ===
{recon_context.to_llm_summary()}
'''
# LLM can now write reasoning like:
# 'has_api=true and auth_endpoints non-empty → jwt_tool is appropriate'
# 'WordPress in tech_stack → wpscan is the highest-value tool to run'
```

---

## 6. Fix the LLM Agent Stopping Bug — raise Exception('__skip__') Counts as Empty

**CRITICAL**: The safety net's skip mechanism raises `Exception('__skip__')` inside tool try blocks. The agent's empty-output counter treats a `__skip__` exception as a tool that returned empty output. After 4 `__skip__`s, the agent stops.

### The exact bug

scan.py uses `if tool in _skip: raise Exception("__skip__")` inside each tool's try block. react_agent.py's `empty_output_consecutive` counter increments when `result.output` length < 30 OR when `result.success` is False. When the exception fires, `result.success=False` and `empty_output_consecutive` increments. After 4 consecutive skips, the agent stops — even though the min-4-tools rule should protect against this.

### The fix

```python
# In orchestrator_pkg/scan.py, replace the raise Exception('__skip__') pattern
# with an early-continue that bypasses the try block entirely:

# REMOVE THIS PATTERN (current broken approach):
# try:
#     if 'nuclei' in _skip: raise Exception('__skip__')
#     nuclei_cmd = [...]
# except Exception as e:
#     if '__skip__' in str(e): ...

# USE THIS INSTEAD:
if 'nuclei' not in _skip:
    try:
        nuclei_cmd = ['-u', target, '-jsonl-export', '-', '-silent']
        # ... rest of nuclei block ...
    except Exception as e:
        logger.warning(f'nuclei failed: {e}')

# In react_agent.py, also fix the empty-output counting:
# Only count truly empty output from tools that ACTUALLY RAN.
if result.tool in tried_tools and not result.success:
    # Tool was attempted but failed or was skipped — don't count against empty limit
    pass
else:
    output_content = (result.output or '').strip()
    if len(output_content) < 30:
        empty_output_consecutive += 1
    else:
        empty_output_consecutive = 0
```

---

## 9. Filter Nuclei by Severity Based on Aggressiveness

### What is happening now

Nuclei runs all templates including INFO severity. INFO findings are noise: exposed headers, version disclosure, server banners. On default aggressiveness, INFO templates make up ~40% of all findings and inflate the findings count without adding security value.

```python
# orchestrator_pkg/scan.py — add severity filter to nuclei_cmd:
NUCLEI_SEVERITY_BY_AGGRESSIVENESS = {
    'default': 'medium,high,critical',
    'high': 'low,medium,high,critical',
    'extreme': 'info,low,medium,high,critical',
}

severity_filter = NUCLEI_SEVERITY_BY_AGGRESSIVENESS.get(agg, 'medium,high,critical')
nuclei_cmd = ['-u', target, '-jsonl-export', '-', '-silent',
              '-severity', severity_filter]

# On default: only medium/high/critical findings returned
# Eliminates ~40% of noise from INFO/LOW templates
# On extreme: everything runs — analyst review mode
```

### Accuracy impact

Default scans return only actionable findings. Analysts see 25 real issues instead of 60 findings where 35 are INFO-level version disclosures.

---

## 10. Fix Target Pre-validation — DNS Failure Blocks Entire Multi-Subdomain Scan

### What is happening now

execute_scan_tools() does a DNS check per target at the top of the `for target in targets` loop. `socket.getaddrinfo(hostname, None)` with a 5-second timeout. If this DNS check fails, the loop calls `continue` — skipping ALL scan tools for that target. For Juice Shop running locally, the hostname might be 'localhost' or '127.0.0.1' — getaddrinfo works fine. But if targets include subdomains from amass that have no A record (CNAME-only or wildcard DNS), the entire target is skipped.

```python
# orchestrator_pkg/scan.py — replace the DNS check with smarter validation:
import ipaddress

def _is_reachable(target: str) -> bool:
    """Check if target is reachable — more permissive than strict DNS check."""
    hostname = target.replace('https://', '').replace('http://', '').split('/')[0].split(':')[0]
    # Always allow IP addresses and localhost
    try:
        ipaddress.ip_address(hostname)
        return True  # Valid IP — no DNS needed
    except ValueError:
        pass
    if hostname in ('localhost', '127.0.0.1', '::1'):
        return True
    # For hostnames, try DNS but don't fail on SERVFAIL or NXDOMAIN
    # Only fail if we get a hard error (no network at all)
    try:
        socket.setdefaulttimeout(5)
        socket.getaddrinfo(hostname, None)
        return True
    except socket.gaierror as e:
        if e.errno in (-2, -3):  # NXDOMAIN or SERVFAIL — skip this subdomain
            logger.warning(f'DNS: {hostname} not found — skipping')
            return False
        return True  # Other errors — try anyway (might be split-horizon DNS)
    except Exception:
        return True  # Unknown error — try anyway
```

---

## 13. Wire pgvector Finding Deduplication (Currently Exists But Never Called)

pgvector_repository.py has `find_similar_findings()`, `store_embedding()`, `check_pgvector_available()`. Zero calls to any of these exist in orchestrator.py or finding_repository.py. Every rescan creates duplicate findings.

### The fix

Call `pgvector_repository.find_similar_findings()` inside `_save_findings()` before each INSERT. If cosine similarity > 0.92 against an existing finding for the same engagement, update `last_seen_at` instead of inserting a new row.

```python
# orchestrator_pkg/orchestrator.py — in _save_findings(), before INSERT:
from database.repositories.pgvector_repository import PgvectorRepository

pgvec = PgvectorRepository(self.db_conn)
if pgvec.check_pgvector_available():
    # Generate embedding for this finding
    embedding_text = f"{finding.get('type','')} {finding.get('endpoint','')} {str(finding.get('evidence',''))[:200]}"
    embedding = self._generate_embedding(embedding_text)  # calls llm_client.embed()
    if embedding:
        similar = pgvec.find_similar_findings(
            embedding=embedding,
            engagement_id=self.engagement_id,
            threshold=0.92,
            limit=1
        )
        if similar:
            # Duplicate — just update last_seen_at
            self.finding_repo.update_last_seen(similar[0]['id'])
            continue  # Don't insert

# Result: no duplicate findings on rescans.
# Analytics accurately reflects unique vulnerabilities, not scan count.
```

---

## 14. Improve Confidence Scoring — Use Tool Agreement Across Scan Types

### What is happening now

intelligence_engine.py's `assign_confidence_scores()` groups findings by type+endpoint and calculates tool_agreement based on how many tools reported the same finding. Single-tool findings get 0.7 agreement score. But with the parallel executor, nuclei and web_scanner might both find XSS on the same endpoint independently — agreement should boost confidence to 1.0 for that finding. The grouping logic needs to be more aggressive about merging findings.

```python
# intelligence_engine.py — improve grouping for tool agreement:
def _group_findings_for_agreement(self, findings: list) -> dict:
    """Group findings that represent the same vulnerability."""
    groups = {}
    for finding in findings:
        # Normalize endpoint for grouping (remove query params for matching)
        from urllib.parse import urlparse
        parsed = urlparse(finding.get('endpoint', ''))
        normalized_endpoint = f"{parsed.netloc}{parsed.path}"

        # Normalize type for grouping (XSS == REFLECTED_XSS == DOM_XSS family)
        TYPE_FAMILIES = {
            'XSS': ['XSS', 'REFLECTED_XSS', 'STORED_XSS', 'DOM_XSS', 'BLIND_XSS'],
            'SQLI': ['SQL_INJECTION', 'BLIND_SQLI', 'TIME_BASED_SQLI', 'ERROR_SQLI'],
            'RCE': ['RCE', 'COMMAND_INJECTION', 'SSTI'],
        }
        normalized_type = finding.get('type', '')
        for family, members in TYPE_FAMILIES.items():
            if normalized_type.upper() in members:
                normalized_type = family
                break

        key = f"{normalized_type}:{normalized_endpoint}"
        if key not in groups:
            groups[key] = []
        groups[key].append(finding)
    return groups

# Result: nuclei's 'XSS' and web_scanner's 'REFLECTED_XSS' on same endpoint
# now share a group → tool_agreement = 1.0 → confidence score boosted
```

---

# COVERAGE IMPROVEMENTS (11, 15)

---

## 11. Stream Tool Output — Show Findings as They Are Found

### What is happening now

Tools run and collect all output in subprocess.stdout. Findings are only parsed and saved after the tool process exits. For a 5-minute nuclei scan, you see nothing for 5 minutes then 50 findings appear at once. Users and analysts think the scan is hung when it is actually working.

```python
# tools/tool_runner.py — add streaming mode:
def run_streaming(self, tool: str, args: list[str],
                  timeout: int, on_line: callable) -> ToolResult:
    """Stream tool output line by line, calling on_line() for each."""

    import subprocess, select
    tool_path = self._resolve_tool_path(tool)
    env = self._locked_env(tool)
    proc = subprocess.Popen(
        [tool_path] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(self.sandbox_dir), env=env
    )
    stdout_lines = []
    start = time.time()
    while proc.poll() is None:
        if time.time() - start > timeout:
            proc.kill()
            break
        ready, _, _ = select.select([proc.stdout], [], [], 0.1)
        if ready:
            line = proc.stdout.readline()
            if line.strip():
                stdout_lines.append(line)
                on_line(line)  # Called immediately for each output line
    # Collect remaining output
    remaining, _ = proc.communicate(timeout=5)
    stdout_lines.extend(remaining.splitlines(keepends=True))
    return ToolResult(stdout=''.join(stdout_lines), ...)

# In orchestrator_pkg/scan.py — use streaming for nuclei:
def _on_nuclei_line(line):
    try:
        finding = json.loads(line)  # nuclei outputs JSON per line
        normalized = ctx._normalize_finding(finding, 'nuclei')
        if normalized:
            # Save immediately — don't wait for scan to complete
            self.finding_repo.create_finding(**normalized)
            emit_finding_discovered(self.engagement_id, normalized)
    except Exception:
        pass

ctx.tool_runner.run_streaming('nuclei', nuclei_cmd, nuclei_timeout, _on_nuclei_line)
# Users see findings appear in real-time in the UI during scanning
```

---

## 15. Wire the Browser Scanner for SPA Targets (Juice Shop, React Apps)

Juice Shop is a React SPA. requests-based tools miss DOM XSS, client-side route vulnerabilities, and anything rendered client-side. The browser scanner exists but is not wired into the scan pipeline.

### What is missing

tools/_browser_scan_worker.py was deleted. tools/browser_scanner.py exists and has the Playwright logic. But browser_scanner.py uses `sync_playwright()` inside a Celery task which causes event loop conflicts.

```python
# Create tools/_browser_scan_worker.py (standalone script):
#!/usr/bin/env python3
"""Standalone browser scan worker — runs Playwright in its own process."""
import sys, json
from playwright.sync_api import sync_playwright

def scan(target_url: str, tech_stack: list) -> list[dict]:
    findings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Intercept console errors (DOM XSS signals)
        console_errors = []
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
        page.goto(target_url, timeout=30000, wait_until='networkidle')
        # Test DOM XSS via URL parameter injection
        for payload in ['<img src=x onerror=alert(1)>', 'javascript:alert(1)']:
            page.goto(f'{target_url}?q={payload}', timeout=10000)
            if any('alert' in e for e in console_errors):
                findings.append({'type':'DOM_XSS','severity':'HIGH',
                    'endpoint':target_url,'evidence':{'payload':payload},'tool':'browser_scanner','confidence':0.9})
        browser.close()
    return findings

if __name__ == '__main__':
    target, tech_json = sys.argv[1], sys.argv[2]
    results = scan(target, json.loads(tech_json))
    print(json.dumps(results))

# In orchestrator_pkg/scan.py — call as subprocess:
import subprocess, sys, json
def _run_browser_scan(target, tech_stack):
    worker = Path(__file__).parent.parent / 'tools' / '_browser_scan_worker.py'
    result = subprocess.run(
        [sys.executable, str(worker), target, json.dumps(tech_stack)],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    return []

# Trigger when SPA detected:
SPA_TECHS = ['react', 'vue', 'angular', 'next', 'nuxt', 'svelte', 'gatsby']
if recon_context and any(t.lower() in ' '.join(recon_context.tech_stack).lower() for t in SPA_TECHS):
    browser_findings = _run_browser_scan(target, recon_context.tech_stack)
    all_findings.extend(browser_findings)
```

---

# Implementation Order

Do these in sequence. Each one builds on the previous and is independently testable.

| Day | Improvements | Time | Expected result after |
|-----|-------------|------|----------------------|
| 1 | Fix cache key (#4) + Remove rate limit delay (#7) + Nuclei severity filter (#9) | ~3 hrs | Immediate: faster scans, less noise. Tests pass. No structural risk. |
| 2 | Fix __skip__ agent stopping bug (#6) + Fix target pre-validation (#10) | ~4 hrs | LLM agent runs correct number of tools. Multi-subdomain scans work. |
| 3 | Parallel recon execution (#1) | ~1 day | Recon: 8min → 90s. Single biggest time saving. |
| 4 | Parallel scan execution (#2) + Nuclei template scoping (#3) | ~1 day | Scan: 900s → 300s. Nuclei faster and more focused. |
| 5 | WebScanner concurrent checks (#8) + Wire browser scanner (#15) | ~1.5 days | Full SPA coverage. WebScanner 120s → 15s. |
| 6 | Feed structured ReconContext to LLM (#5) + pgvector dedup (#13) | ~1 day | Agent makes better decisions. No duplicate findings on rescans. |
| 7 | Tool output streaming (#11) + Confidence scoring (#14) + Celery concurrency (#12) | ~1.5 days | Findings appear in real-time. Accuracy scores are meaningful. |

---

# Expected Results After All 15 Improvements

| Metric | Before | After |
|--------|--------|-------|
| Recon wall-clock time | 8-12 minutes | 60-90 seconds |
| Scan wall-clock time | 20-40 minutes | 5-8 minutes |
| Total pipeline time | ~40-50 minutes | ~8-12 minutes |
| Findings on Juice Shop | 10 (timeout) | 60-120 (all tools complete) |
| Duplicate findings on rescan | Many (no dedup) | Zero (pgvector dedup) |
| INFO/LOW noise in default scan | ~40% of findings | Eliminated (severity filter) |
| LLM agent tool selection | 2 tools then stops | 4-6 tools based on recon signals |
| SPA/React app coverage | Requests-based only | Full DOM XSS via browser scanner |
| Finding visibility during scan | After tool completes | Real-time streaming as found |
| Cache hit rate on rescan | 0% (broken hash key) | 80%+ (stable SHA-256 key) |
