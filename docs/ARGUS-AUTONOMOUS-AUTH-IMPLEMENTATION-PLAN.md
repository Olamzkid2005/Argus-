# Argus Autonomous Registration & Login — Implementation Plan

## Overview

Add two new agent tools (`register`, `login`) and an `AuthContext` that lets the LLM agent autonomously create accounts, log in, and pass authentication to all existing scan tools.

### Why This Matters

Currently, the Argus agent can only run tools against public/unauthenticated pages. The LLM can reason about needing credentials — it just has no tools to obtain them. This plan gives the agent the ability to:

1. Discover registration and login forms autonomously
2. Generate random test credentials and register
3. Log in and capture session cookies/JWT tokens
4. Pass authentication to all existing scan tools (sqlmap, nuclei, dalfox, etc.)

---

## Architecture

```
Agent decides: "I need credentials"
        │
        ▼
  register(target="https://vulnbank.org")
        │
        ├── 1. Discover registration form (hybrid: recon data + common paths)
        ├── 2. Extract form fields (email, password, CSRF token)
        ├── 3. Generate random credentials
        ├── 4. Submit registration form
        ├── 5. Try logging in immediately
        └── 6. Return AuthContext with session
        │
        ▼
  login(target, email, password) [optional — register already logs in]
        │
        ├── 1. Discover login form
        ├── 2. Submit credentials
        ├── 3. Capture session cookies + JWT
        └── 4. Return AuthContext with session
        │
        ▼
  AuthContext stored on agent
        │
        ▼
  sqlmap(target, args) ──→ inject_auth() adds --cookie
  dalfox(target, args) ──→ inject_auth() adds --cookie  
  nuclei(target, args) ──→ inject_auth() adds -H "Cookie: ..."
  web_scanner(target) ───→ session passed directly (Phase B)
```

### Agent Decision Flow — When Does the Agent Choose Auth?

```
Scan phase starts
        │
        ├── Does engagement already have auth_config? (from AuthWizard UI)
        │     └── YES → Skip register/login. AuthManager handles session.
        │                    Agent proceeds directly to tool selection.
        │
        ├── Does recon data show registration/login forms?
        │     └── NO  → Skip register/login. Proceed unauthenticated.
        │
        ├── Call register(target)
        │     ├── Success + auto-login → AuthContext stored → Proceed authenticated
        │     ├── Needs verification → Try login() once → If fails, report finding
        │     └── Failed (CAPTCHA/no form) → Report finding → Proceed unauthenticated
        │
        └── Agent selects tools with auth injected automatically
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Phase** | `scan` phase | Registration/login happen before authenticated scanning |
| **Session storage** | Agent context (`AuthContext`) | Keeps auth at agent layer, tools remain unaware |
| **Auth injection** | Tool wrapper closure | No changes to `ToolRunner.run()` API; backward compatible |
| **Auth injection strategy** | `TOOL_AUTH_INJECTORS` dict | Prevents growing if/elif chain; each tool has own injector |
| **Credential strategy** | Auto-generate with optional override | Fully autonomous; user can provide base credentials if needed |
| **Email verification** | Multi-tier fallback | Detect → try login anyway → report finding |
| **Retry count** | 3 for all retryable errors | Consistent; matches standard retry patterns |
| **Form discovery** | Hybrid (recon data + common paths) | Fast when recon data exists, robust fallback when it doesn't |
| **Error reporting** | Rich structured stdout + error codes | LLM reads stdout to adapt on unexpected responses |
| **AuthManager priority** | Pre-configured auth > agent auth | User-provided credentials are always more reliable |
| **Rate limiting** | Jittered exponential backoff | Avoids triggering anti-bot measures on retry |
| **Session persistence** | Checkpoint serialization | Survives Celery worker restarts |

---

## Refinement 1: Granular Implementation Phases with Commit Points

Each phase is independently committable. Each commit must pass all existing tests before the next phase begins.

```
Phase 1a: AuthContext dataclass               → commit "feat: add AuthContext dataclass"
Phase 1b: requests + beautifulsoup4 deps      → commit "chore: add auth dependencies"
Phase 2a: Tool definitions (register + login) → commit "feat: register + login tool definitions"
Phase 2b: Skeleton tool registration in agent → commit "feat: wire register/login skeletons into agent"
Phase 3a: Form discovery utility              → commit "feat: add form discovery utility"
Phase 3b: Form discovery tests                → commit "test: form discovery unit tests"
Phase 4a: Auth injectors                      → commit "feat: add tool auth injectors"
Phase 4b: Auth injector tests                 → commit "test: auth injector unit tests"
Phase 5a: Register tool — credential gen      → commit "feat: add credential generation"
Phase 5b: Register tool — form submission     → commit "feat: implement register tool form submission"
Phase 5c: Register tool — tests               → commit "test: register tool unit tests"
Phase 6a: Login tool — form submission        → commit "feat: implement login tool"
Phase 6b: Login tool — tests                  → commit "test: login tool unit tests"
Phase 7a: Full agent wiring + session flow    → commit "feat: wire auth session through agent"
Phase 7b: Celery retry persistence            → commit "feat: persist AuthContext across Celery retry"
Phase 8a: Integration tests                   → commit "test: add auth integration tests"
Phase 8b: Regression tests                    → commit "test: add auth regression tests"
Phase 9:  LLM prompt updates                  → commit "feat: add auth tool guidance to agent prompts"
```

---

## Refinement 2: Dependency Audit

### Required Dependencies

Check and add to `argus-workers/requirements.txt`:

| Package | Required By | Currently Present? | Version |
|---------|------------|-------------------|---------|
| `requests` | HTTP session management | ✅ | >=2.28 |
| `beautifulsoup4` | HTML form parsing | ❌ **ADD** | >=4.12 |
| `lxml` | Fast HTML parser (BS4 backend) | ❌ **ADD** | >=4.9 |
| `bs4` | (alias for beautifulsoup4) | ❌ **ADD** | (same) |

### Verification Command

```bash
cd argus-workers && source venv/bin/activate
pip install beautifulsoup4 lxml
python3 -c "from bs4 import BeautifulSoup; print('OK')"
```

---

## AuthContext Object

### File: `argus-workers/agent/auth_context.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
import requests


@dataclass
class AuthContext:
    """Structured authentication state managed by the agent.
    
    After register() or login() succeeds, the agent stores an AuthContext
    instance. All tool wrappers read from this context to inject auth into
    tool CLI arguments or pass the session object directly.
    
    For Celery retry persistence: this object can be serialized to JSON
    (minus the live `session` which is re-established via login() on retry).
    """
    # Live session (NOT serialized — re-established on retry)
    session: Optional[requests.Session] = None
    
    # Serializable fields
    cookie_string: Optional[str] = None          # "name=value; name2=value2"
    authorization: Optional[str] = None          # "Bearer eyJ..." or "Basic ..."
    csrf_token: Optional[str] = None             # CSRF token if extracted
    email: Optional[str] = None                  # Used credentials (for retry)
    password: Optional[str] = None               # Used credentials (for retry)
    register_url: Optional[str] = None           # Discovered endpoints
    login_url: Optional[str] = None              # Discovered endpoints
    
    def is_authenticated(self) -> bool:
        return self.session is not None
    
    def to_dict(self) -> dict:
        """Serialize to dict (excludes live session)."""
        return {
            "cookie_string": self.cookie_string,
            "authorization": self.authorization,
            "csrf_token": self.csrf_token,
            "email": self.email,
            "password": self.password,
            "register_url": self.register_url,
            "login_url": self.login_url,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AuthContext":
        """Deserialize from dict (session must be re-established)."""
        return cls(
            cookie_string=data.get("cookie_string"),
            authorization=data.get("authorization"),
            csrf_token=data.get("csrf_token"),
            email=data.get("email"),
            password=data.get("password"),
            register_url=data.get("register_url"),
            login_url=data.get("login_url"),
        )
```

### Rollback

If this phase causes import errors: `git checkout -- argus-workers/agent/auth_context.py`

---

## Tool Definitions

### File: `argus-workers/tool_definitions.py`

Add two new `ToolDefinition` entries before the scan phase tool list:

```python
_register(ToolDefinition(
    name="register",
    description="Register a new test account on the target application. "
                "Auto-generates a unique email and password. "
                "Discovers registration form fields automatically. "
                "On success, stores authenticated session for subsequent tools. "
                "Handles email verification fallback gracefully.",
    phases=["scan"],
    parameters=[
        ToolParameter(name="target", description="Base URL", type="string", required=True),
    ],
    timeout=120,
    parallel_safe=False,
    signal_quality=SignalQuality.CONFIRMED,
    exploit_categories=["auth"],
    estimated_cost=0.0,
    estimated_runtime=30,
))

_register(ToolDefinition(
    name="login",
    description="Log in to the target application with stored or provided credentials. "
                "Auto-discovers login form fields. "
                "If email/password omitted, uses credentials from prior register() call. "
                "On success, stores authenticated session for subsequent tools.",
    phases=["scan"],
    parameters=[
        ToolParameter(name="target", description="Base URL", type="string", required=True),
        ToolParameter(name="email", description="Email (auto-fills from register)", type="string", required=False),
        ToolParameter(name="password", description="Password (auto-fills from register)", type="string", required=False),
    ],
    timeout=60,
    parallel_safe=False,
    signal_quality=SignalQuality.CONFIRMED,
    exploit_categories=["auth"],
    estimated_cost=0.0,
    estimated_runtime=15,
))
```

### Rollback

If tool loading fails: `git checkout -- argus-workers/tool_definitions.py`

---

## Form Discovery Utility

### File: `argus-workers/agent/form_discovery.py`

Hybrid approach: checks recon crawl data first, then scans common auth endpoints.

```python
# Common registration endpoint paths
REGISTER_PATHS = [
    "/register", "/signup", "/sign-up", "/create-account",
    "/auth/register", "/api/register", "/api/auth/register",
    "/account/create", "/users/new",
]

# Common login endpoint paths
LOGIN_PATHS = [
    "/login", "/signin", "/sign-in", "/auth/login",
    "/api/login", "/api/auth/login", "/account/login",
    "/auth", "/user/login",
]
```

### Key Functions

| Function | Purpose |
|----------|---------|
| `discover_auth_endpoints(target, session, recon_crawled_paths)` | Returns `{register_url, login_url, register_fields, login_fields}` |
| `_extract_form_fields(html, form_type)` | Parses HTML form → `{email, password, confirm, csrf}` field name mapping |
| `_has_verification_requirement(resp)` | Checks response for email verification prompts |

### Error Codes

```python
ERROR_CODES = {
    "FORM_NOT_FOUND": "No registration/login form discovered",
    "VALIDATION_FAILED": "Form submitted but validation errors returned",
    "CAPTCHA_DETECTED": "CAPTCHA or bot detection blocked operation",
    "EMAIL_VERIFICATION_REQUIRED": "Registration succeeded but email verification required",
    "EMAIL_EXISTS": "Email already registered from prior scan",
    "RATE_LIMITED": "Rate limited during attempt",
    "PASSWORD_REQUIREMENTS": "Password does not meet site requirements",
    "INVALID_CREDENTIALS": "Login rejected — wrong credentials",
    "ACCOUNT_LOCKED": "Account locked or disabled",
    "2FA_REQUIRED": "Two-factor authentication required",
    "SESSION_FAILED": "Login succeeded but no session cookie was set",
    "UNKNOWN_FAILURE": "Operation failed for unspecified reason",
}
```

### Rollback

`git checkout -- argus-workers/agent/form_discovery.py`

---

## Auth Injectors

### File: `argus-workers/agent/auth_injectors.py`

Each tool has its own injector function. Central registry prevents if/elif sprawl.

| Tool | Injection Method | Example |
|------|-----------------|---------|
| `sqlmap` | `--cookie <cookies>` | `sqlmap -u URL --cookie "session=abc"` |
| `dalfox` | `--cookie <cookies>` | `dalfox URL --cookie "session=abc"` |
| `nuclei` | `-H "Cookie: <cookies>"` | `nuclei -u URL -H "Cookie: session=abc"` |
| `ffuf` | `-b <cookies>` | `ffuf -u URL -b "session=abc"` |
| `nikto` | `-Cookie <cookies>` | `nikto -h URL -Cookie "session=abc"` |
| `gospider` | `--cookie <cookies>` | `gospider --cookie "session=abc"` |

### Dedup Guard

Each injector checks if the user/LLM already specified cookie args:

```python
def _has_cookie_flag(args: list[str]) -> bool:
    """Check if args already contain a cookie flag."""
    for i, arg in enumerate(args):
        if arg in ("--cookie", "-b", "-Cookie") and i + 1 < len(args):
            return True
    return False
```

### Interface

```python
def inject_auth(tool_name: str, args: list[str], ctx: AuthContext | None) -> list[str]:
    """Apply auth injection. Returns args unchanged if ctx is None (backward compat)."""
```

### Rollback

`git checkout -- argus-workers/agent/auth_injectors.py`

---

## Register Tool Implementation

### File: `argus-workers/agent/tools/register_tool.py`

### Flow

```
1. discover_auth_endpoints() → find register_url + form fields
2. Generate random email + password
3. Fetch register page (get fresh CSRF token if needed)
4. POST registration form
5. If success → _try_login() with same credentials
6. Return ToolResult + AuthContext
```

### Credential Generation

```python
def generate_credentials() -> tuple[str, str]:
    rand = uuid.uuid4().hex[:8]
    email = f"argus_pentest_{rand}@temp-mail.org"
    password = generate_strong_password()  # 16 chars, mixed case + digits + special
    return email, password
```

### Email Verification Handling

```python
# After registration succeeds:
login_result = _try_login(target, session, email, password, endpoints)

if login_result["success"]:
    # ✅ Fully authenticated — proceed
elif login_result.get("requires_verification"):
    # ⚠️ Registration worked but email verification needed
    # Try login anyway (some apps allow it)
    # If fails → report finding, continue unauthenticated
```

### Retry Logic

| Error | Retry? | Behavior |
|-------|--------|----------|
| FORM_NOT_FOUND | ❌ | Report finding, skip auth |
| CAPTCHA_DETECTED | ❌ | Report finding, skip auth |
| VALIDATION_FAILED | ✅ (3x) | Different field patterns, retry |
| EMAIL_EXISTS | ✅ (3x) | New email each attempt |
| RATE_LIMITED | ✅ (3x, jittered backoff) | Wait 5-15s → 30-60s → 60-120s |
| EMAIL_VERIFICATION_REQUIRED | ✅ (1x) | Try login once, then report |
| UNKNOWN | ✅ (3x) | Retry with backoff |

### Rollback

`git checkout -- argus-workers/agent/tools/register_tool.py`

---

## Login Tool Implementation

### File: `argus-workers/agent/tools/login_tool.py`

### Flow

```
1. Check for credentials (provided or from AuthContext)
2. discover_auth_endpoints() → find login_url + form fields
3. If no credentials → return error: "Call register() first"
4. POST login form with credentials
5. Check response for:
   - Invalid credentials → retry (3x)
   - 2FA required → report finding
   - Account locked → report finding
   - Rate limited → backoff and retry
   - Success → capture session cookies + extract JWT
6. Return ToolResult + AuthContext
```

### JWT Extraction

```python
for c in http_session.cookies:
    if c.name.lower() in ("token", "jwt", "access_token", "authorization"):
        ctx.authorization = f"Bearer {c.value}"
```

### Rollback

`git checkout -- argus-workers/agent/tools/login_tool.py`

---

## Wire Into ReActAgent

### File: `argus-workers/agent/react_agent.py`

### Changes

1. **Add `_auth_context` to `__init__`**:
```python
self._auth_context: AuthContext | None = None
```

2. **Add `set_auth_context` method**:
```python
def set_auth_context(self, ctx: AuthContext):
    self._auth_context = ctx
```

3. **Modify `make_runner` closure** (in `create_for_phase`):
```python
def make_runner(tn):
    def run_tool(target: str = "", **kwargs):
        args = kwargs.pop("args", [])
        timeout = kwargs.pop("timeout", 300)
        if target:
            args = [target] + (args or [])
        
        # NEW: Inject auth context for tools that support it
        if self._auth_context:
            args = inject_auth(tn, args, self._auth_context)
        
        return tool_runner.run(tn, args, timeout=timeout)
    run_tool.__name__ = tn
    return run_tool
```

4. **Register `register` and `login` tools** (in `create_for_phase`, scan phase only):
```python
if phase == "scan":
    registry.register("register", make_register_tool(), metadata={...})
    registry.register("login", make_login_tool(), metadata={...})
```

5. **Wire tool results back** — after `register`/`login` execute, call `set_auth_context()` with the returned `AuthContext`.

### Interaction with Existing AuthManager (Refinement 5)

In `orchestrator.py`'s `_run_scan_with_fallback`, before the agent runs:

```python
# If user pre-configured auth via AuthWizard, skip agent registration
if auth_config:
    logger.info("Pre-configured auth detected — skipping agent register/login")
    # AuthManager already handles session in the deterministic fallback path
    # Agent proceeds directly to tool selection without register/login tools
```

In `create_for_phase`, when `auth_config` is present, do NOT register `register`/`login` tools — the agent never sees them.

### Rollback

This is the highest-risk change. If the agent breaks:
```bash
git checkout -- argus-workers/agent/react_agent.py
```
Then verify: `cd argus-workers && source venv/bin/activate && pytest tests/ -x -q`

---

## Refinement 6: Session Persistence Across Celery Retry

### Problem

If the Celery worker crashes after `register`/`login` succeeds but before the scan completes, the session is lost. On retry, the agent has no `AuthContext`.

### Solution

1. **After `register`/`login` succeeds**, serialize `AuthContext.to_dict()` (all fields except the live `session`) to the agent's checkpoint store.

2. **On agent initialization** (in `decide_next_action`), check for a stored checkpoint:
```python
if self._auth_context is None:
    checkpoint = self._load_auth_checkpoint()
    if checkpoint:
        # Re-establish session by logging in with stored credentials
        result, ctx = run_login(
            target=self._current_target,
            http_session=requests.Session(),
            email=checkpoint.email,
            password=checkpoint.password,
        )
        if ctx and ctx.is_authenticated():
            self.set_auth_context(ctx)
```

3. **Where to store**: Use the existing `DecisionCheckpointRepository` in `runtime/decision_checkpoint.py`:
```python
from runtime.decision_checkpoint import DecisionCheckpointRepository
repo = DecisionCheckpointRepository()
repo.save_checkpoint(
    engagement_id=self.engagement_id,
    checkpoint_type="auth_context",
    data=ctx.to_dict(),
)
```

### Rollback

Revert the checkpoint read/write logic. The worst case on retry is the agent re-attempts register/login.

---

## Refinement 7: Rate Limiting — Jittered Exponential Backoff

### Strategy

```python
import random
import time

BACKOFF_DELAYS = [5, 30, 60]  # seconds per attempt (1-indexed)

def rate_limit_backoff(attempt: int):
    """Sleep with jittered backoff based on attempt number (0-indexed)."""
    if attempt >= len(BACKOFF_DELAYS):
        delay = BACKOFF_DELAYS[-1]
    else:
        delay = BACKOFF_DELAYS[attempt]
    jitter = random.uniform(0.5, 1.5)  # ±50% jitter
    time.sleep(delay * jitter)
```

Applied in both `register_tool.py` and `login_tool.py` when `RATE_LIMITED` error is detected:

```python
if error_code == "RATE_LIMITED" and attempt < MAX_RETRIES - 1:
    rate_limit_backoff(attempt)
    continue
```

---

## Refinement 8: LLM Prompt Updates

### File: `argus-workers/agent/agent_prompts.py`

Add auth guidance to the scan phase system prompt (`TOOL_SELECTION_SYSTEM_PROMPT` or `build_tech_aware_system_prompt`):

```python
AUTH_GUIDANCE = """
### Authentication Tools Available
You have `register` and `login` tools available in this phase.

Use `register` when:
  - Recon discovered a registration form (/register, /signup, etc.)
  - You need authenticated access to test protected endpoints
  - You don't have existing credentials

Use `login` when:
  - You already have credentials (from register or provided config)
  - You need to re-establish a session after a failure

Strategy:
  1. If the site has registration, call register() first.
  2. register() auto-logs in on success — proceed to other tools.
  3. If register() returns needs_verification, call login() with the
     returned email/password. Some apps work without verification.
  4. If all auth attempts fail, generate a finding and continue with
     unauthenticated testing. Partial coverage is better than none.

IMPORTANT: Do NOT call register() or login() repeatedly. If auth fails
after retries, move on to other tools.
"""
```

Append this to the system prompt when `register` and `login` tools are registered (i.e., scan phase without pre-configured `auth_config`).

### Rollback

Remove the `AUTH_GUIDANCE` constant and its injection point.

---

## Web Scanner Special Case

`web_scanner` accepts a `requests.Session` object directly (not CLI args). In the deterministic fallback pipeline within `scan.py`, the authenticated session from `AuthManager` is already passed. No changes needed for the agent path — the agent calls nuclei/dalfox/sqlmap via CLI, and `web_scanner` runs via the safety-net deterministic pass.

---

## Testing Strategy

### Unit Tests

| Test | File | What It Verifies |
|------|------|------------------|
| `test_auth_context_defaults` | `test_auth_context.py` | All fields default to None |
| `test_auth_context_is_authenticated` | `test_auth_context.py` | False when no session, True after |
| `test_auth_context_serialize` | `test_auth_context.py` | to_dict/from_dict round-trips correctly |
| `test_extract_form_fields_standard` | `test_form_discovery.py` | Parses login form correctly |
| `test_extract_form_fields_csrf` | `test_form_discovery.py` | Detects CSRF token field |
| `test_extract_form_fields_confirm_password` | `test_form_discovery.py` | Distinguishes password vs confirm |
| `test_discover_auth_endpoints_recon` | `test_form_discovery.py` | Uses recon data first |
| `test_discover_auth_endpoints_fallback` | `test_form_discovery.py` | Falls back to common paths |
| `test_inject_sqlmap_cookie` | `test_auth_injectors.py` | Adds --cookie correctly |
| `test_inject_sqlmap_no_duplicate` | `test_auth_injectors.py` | Does NOT double-inject |
| `test_inject_nuclei_header` | `test_auth_injectors.py` | Adds -H "Cookie: ..." |
| `test_inject_auth_no_context` | `test_auth_injectors.py` | Returns args unchanged when ctx=None |
| `test_register_no_form` | `test_register_tool.py` | Failure when no register URL |
| `test_register_success` | `test_register_tool.py` | Returns AuthContext with session |
| `test_register_email_exists_retry` | `test_register_tool.py` | Retries on duplicate email |
| `test_register_captcha_breaks` | `test_register_tool.py` | No retry on CAPTCHA |
| `test_register_password_strength` | `test_register_tool.py` | Generated password meets requirements |
| `test_register_rate_limit_backoff` | `test_register_tool.py` | Jittered backoff on rate limit |
| `test_login_no_credentials` | `test_login_tool.py` | Failure when no credentials |
| `test_login_no_form` | `test_login_tool.py` | Failure when no login URL |
| `test_login_success` | `test_login_tool.py` | Returns AuthContext with session |
| `test_login_2fa_detected` | `test_login_tool.py` | Detects 2FA requirement |
| `test_login_account_locked` | `test_login_tool.py` | Detects locked account |
| `test_login_retry_invalid` | `test_login_tool.py` | Retries on invalid credentials |
| `test_agent_auth_context_init` | `test_react_agent.py` | Agent starts with None |
| `test_agent_set_auth_context` | `test_react_agent.py` | Stores context on agent |
| `test_agent_wrapper_injects_auth` | `test_react_agent.py` | Auth injected when context set |
| `test_agent_wrapper_no_inject` | `test_react_agent.py` | No injection when ctx=None |
| `test_agent_register_in_scan_phase` | `test_react_agent.py` | Register tool in scan phase registry |
| `test_agent_login_in_scan_phase` | `test_react_agent.py` | Login tool in scan phase registry |
| `test_agent_register_not_in_recon` | `test_react_agent.py` | Register NOT in recon phase |
| `test_agent_authmanager_skips_register` | `test_react_agent.py` | No register/login when auth_config preset |
| `test_checkpoint_serialize` | `test_auth_context.py` | Checkpoint survives JSON round-trip |

### Integration Tests

| Test | What It Verifies |
|------|------------------|
| `test_full_auth_flow` | Recon → register → login → sqlmap with cookies |
| `test_register_then_scan` | After register, sqlmap/nuclei/dalfox receive cookies |
| `test_web_scanner_session` | Session passes to web_scanner in fallback |
| `test_auth_survives_retry` | AuthContext restored from checkpoint on retry |
| `test_authmanager_supersedes_agent` | Pre-configured auth_config prevents agent register |

### Regression Tests

| Test | What It Verifies |
|------|------------------|
| `test_existing_scan_no_auth` | Existing scan without auth — no injection happens |
| `test_existing_scan_with_authmanager` | Existing scan with AuthManager — no double-injection |
| `test_all_existing_unit_tests_pass` | All prior tests still pass |

---

## Files Changed Summary

| File | Action | Est. Lines | Risk | Rollback Command |
|------|--------|------------|------|------------------|
| `argus-workers/agent/auth_context.py` | **Create** | 60 | Low | `git checkout -- agent/auth_context.py` |
| `argus-workers/agent/form_discovery.py` | **Create** | 220 | Low | `git checkout -- agent/form_discovery.py` |
| `argus-workers/agent/auth_injectors.py` | **Create** | 120 | Low | `git checkout -- agent/auth_injectors.py` |
| `argus-workers/agent/tools/register_tool.py` | **Create** | 220 | Medium | `git checkout -- agent/tools/register_tool.py` |
| `argus-workers/agent/tools/login_tool.py` | **Create** | 190 | Medium | `git checkout -- agent/tools/login_tool.py` |
| `argus-workers/tool_definitions.py` | **Edit** | 40 | Low | `git checkout -- tool_definitions.py` |
| `argus-workers/agent/react_agent.py` | **Edit** | 90 | **High** | `git checkout -- agent/react_agent.py` |
| `argus-workers/agent/agent_prompts.py` | **Edit** | 25 | Low | `git checkout -- agent/agent_prompts.py` |
| `argus-workers/requirements.txt` | **Edit** | 2 | Low | `git checkout -- requirements.txt` |
| Tests (various) | **Create/Edit** | 450 | N/A | `git checkout -- tests/` |

**Total**: ~1,417 lines production code, ~450 lines tests, ~29 independently committable phases

---

## Implementation Order with Verification Gates

```
Phase 1a: AuthContext dataclass
  → Verify: python3 -c "from agent.auth_context import AuthContext; print('OK')"
  → Commit: "feat: add AuthContext dataclass"
  
Phase 1b: Install + verify dependencies
  → Verify: python3 -c "from bs4 import BeautifulSoup; print('OK')"
  → Commit: "chore: add beautifulsoup4 + lxml dependencies"
  
Phase 2a: Tool definitions
  → Verify: python3 -c "from tool_definitions import get_phase_tool_names; print(get_phase_tool_names('scan'))"
  → Commit: "feat: add register + login tool definitions"
  
Phase 2b: Skeleton registration
  → Verify: pytest tests/test_react_agent.py -x -q -k "register_in_scan"
  → Commit: "feat: wire register/login skeletons into agent"
  
Phase 3a: Form discovery
  → Verify: pytest tests/test_form_discovery.py -x -q
  → Commit: "feat: add form discovery utility"
  
Phase 4a: Auth injectors
  → Verify: pytest tests/test_auth_injectors.py -x -q
  → Commit: "feat: add tool auth injectors"
  
Phase 5a: Register tool (credential gen)
  → Verify: pytest tests/test_register_tool.py -x -q -k "password_strength"
  → Commit: "feat: add credential generation"
  
Phase 5b: Register tool (full)
  → Verify: pytest tests/test_register_tool.py -x -q
  → Commit: "feat: implement register tool"
  
Phase 6a: Login tool
  → Verify: pytest tests/test_login_tool.py -x -q
  → Commit: "feat: implement login tool"
  
Phase 7a: Full agent wiring
  → Verify: pytest tests/test_react_agent.py -x -q -k "auth"
  → Commit: "feat: wire auth session through agent"
  
Phase 7b: Celery retry persistence
  → Verify: pytest tests/test_auth_context.py -x -q -k "checkpoint"
  → Commit: "feat: persist AuthContext across Celery retry"
  
Phase 8: Integration tests
  → Verify: pytest tests/integration/test_auth_flow.py -x -q
  → Commit: "test: add auth integration tests"
  
Phase 9: Regression suite
  → Verify: pytest tests/ -x -q (ALL tests pass)
  → Commit: "test: verify all existing tests pass with auth changes"
  
Phase 10: LLM prompt update
  → Verify: grep "register\|login" argus-workers/agent/agent_prompts.py
  → Commit: "feat: add auth tool guidance to agent prompts"
```

---

## Backward Compatibility & Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Auth injection breaks existing scan | Low | High | `inject_auth()` is NO-OP when `_auth_context` is `None` |
| Double-injection of cookies | Medium | Medium | `_has_cookie_flag()` guard prevents duplicates |
| Register/login tools fire in wrong phase | Low | Low | Tools only registered during `scan` phase |
| HTML parsing crash on weird form | Low | Low | All parsing wrapped in try/except |
| Session leaks across engagements | Low | Medium | Per-agent-instance AuthContext |
| Celery retry loses session state | Medium | Medium | Checkpoint serialization + re-login on retry |
| Agent wastes time on register when auth pre-configured | Low | Low | `auth_config` presence skips register/login tool registration entirely |
| Rate limiting triggers account lockout | Low | Medium | Jittered backoff + 3 retry max + CAPTCHA detection breaks early |
| beautifulsoup4 not installed on target env | Low | High | Added to requirements.txt; verified in Phase 1b |
| LLM calls register() repeatedly | Low | Low | Prompt guidance says "Do NOT call repeatedly"; tool tracks attempts |
