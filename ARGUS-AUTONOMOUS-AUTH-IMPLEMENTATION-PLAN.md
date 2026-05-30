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

---

## AuthContext Object

### File: `argus-workers/agent/auth_context.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import requests


@dataclass
class AuthContext:
    """Structured authentication state managed by the agent.
    
    After register() or login() succeeds, the agent stores an AuthContext
    instance. All tool wrappers read from this context to inject auth into
    tool CLI arguments or pass the session object directly.
    """
    session: requests.Session | None = None          # Full requests.Session
    cookie_string: str | None = None                 # "name=value; name2=value2"
    authorization: str | None = None                 # "Bearer eyJ..." or "Basic ..."
    csrf_token: str | None = None                    # CSRF token if extracted
    email: str | None = None                         # Used credentials (for retry)
    password: str | None = None                      # Used credentials (for retry)
    register_url: str | None = None                  # Discovered endpoints
    login_url: str | None = None                     # Discovered endpoints
    
    def is_authenticated(self) -> bool:
        return self.session is not None
```

---

## Tool Definitions

### File: `argus-workers/tool_definitions.py`

Add two new `ToolDefinition` entries:

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
| RATE_LIMITED | ✅ (3x, 30s backoff) | Wait and retry |
| EMAIL_VERIFICATION_REQUIRED | ✅ (1x) | Try login once, then report |
| UNKNOWN | ✅ (3x) | Retry with backoff |

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

### Integration Tests

| Test | What It Verifies |
|------|------------------|
| `test_full_auth_flow` | Recon → register → login → sqlmap with cookies |
| `test_web_scanner_session` | Session passes to web_scanner in fallback |
| `test_auth_survives_retry` | AuthContext persists across agent retry |

### Regression Tests

| Test | What It Verifies |
|------|------------------|
| `test_existing_scan_no_auth` | Existing scan without auth — no injection happens |
| `test_existing_scan_with_authmanager` | Existing scan with AuthManager — no double-injection |
| `test_all_existing_unit_tests_pass` | All prior tests still pass |

---

## Files Changed Summary

| File | Action | Est. Lines | Risk |
|------|--------|------------|------|
| `argus-workers/agent/auth_context.py` | **Create** | 45 | Low — standalone dataclass |
| `argus-workers/agent/form_discovery.py` | **Create** | 220 | Low — utility functions |
| `argus-workers/agent/auth_injectors.py` | **Create** | 120 | Low — isolated injector functions |
| `argus-workers/agent/tools/register_tool.py` | **Create** | 200 | Medium — core logic |
| `argus-workers/agent/tools/login_tool.py` | **Create** | 180 | Medium — core logic |
| `argus-workers/tool_definitions.py` | **Edit** | 40 | Low — declarative config |
| `argus-workers/agent/react_agent.py` | **Edit** | 80 | **High** — agent core, must preserve existing flow |
| Tests (various files) | **Create/Edit** | 400 | N/A — no production impact |

**Total**: ~1,285 lines production code, ~400 lines tests

---

## Implementation Order

```
Phase 1: AuthContext dataclass
    ↓
Phase 2: Tool definitions (register + login)
    ↓
Phase 3: Form discovery utility
    ↓
Phase 4: Auth injectors
    ↓
Phase 5: Register tool implementation
    ↓
Phase 6: Login tool implementation
    ↓
Phase 7: Wire into ReActAgent
    ↓
Phase 8: Write all tests
    ↓
Phase 9: Run existing regression suite
    ↓
Phase 10: Run integration tests
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
| Celery retry loses session state | Medium | Medium | Agent re-attempts register/login on retry |
